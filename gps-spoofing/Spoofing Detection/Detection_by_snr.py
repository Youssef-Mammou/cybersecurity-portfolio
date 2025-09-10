#!/usr/bin/env python3
# Détecteur temps réel (NMEA GSV) : affiche SNR par PRN (Matplotlib) et ouvre une alerte Tkinter si anomalies (sauts SNR, PRN nouveaux/disparus).

import tkinter as tk
import threading
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import serial
import pynmea2
import time
from datetime import datetime
from collections import deque

# ---------------- Configuration ----------------
PORT = 'COM4'                       # Port série du récepteur GNSS (ex. COM4)
BAUDRATE = 9600                     # Débit série NMEA courant (adapter si besoin)
STABILIZATION_DURATION = 90         # Durée (s) d’attente avant d’analyser (historiques)
SNR_JUMP_THRESHOLD = 6              # Saut absolu de SNR minimal (dB-Hz) pour signaler un jump
NEW_PRNS_THRESHOLD = 4              # Nb de nouveaux PRN tolérés avant de considérer anomalie
DISAPPEARED_PRNS_THRESHOLD = 4      # Nb de PRN disparus tolérés avant anomalie
ANOMALY_CONFIRMATION_COUNT = 2      # Nb d’itérations consécutives avec anomalies avant alerte
HISTORY_LENGTH = 3                  # Taille de la fenêtre glissante pour moyennes SNR
INSTANT_SHOCK_THRESHOLD = 5         # Déclenchement immédiat si nb de nouveaux PRNs ≥ ce seuil
SNR_MIN_THRESHOLD = 23              # On ignore les sats en dessous de ce SNR (dB-Hz)
MIN_SAT_FOR_ANALYSIS = 4            # On n’analyse pas si < 4 sats filtrés
# ------------------------------------------------

root = tk.Tk()
root.withdraw()  # On cache la fenêtre principale (on n’affiche que la popup d’alerte)
alert_window = None

def show_alert(causes):
    """Crée/affiche une fenêtre d'alerte listant les causes détectées."""
    def create_window():
        global alert_window
        # Si une ancienne alerte existe encore, on la remplace pour éviter les doublons
        if alert_window and alert_window.winfo_exists():
            alert_window.destroy()

        # Fenêtre d’alerte en avant-plan
        alert_window = tk.Toplevel(root)
        alert_window.title("ALERTE SPOOFING")
        alert_window.configure(bg="black")
        alert_window.geometry("800x400+300+150")
        alert_window.attributes("-topmost", True)

        # Titre clair
        title_label = tk.Label(
            alert_window, text="DETECTION SPOOFING",
            font=("Helvetica", 28, "bold"), fg="red", bg="black"
        )
        title_label.pack(pady=20)

        # Liste des causes (nouveaux PRNs, PRNs disparus, sauts de SNR)
        for cause in causes:
            cause_label = tk.Label(
                alert_window, text=cause,
                font=("Helvetica", 14), fg="white", bg="black", wraplength=760
            )
            cause_label.pack()

    root.after(0, create_window)

def worker():
    """Lit le port série, met à jour l'historique SNR/PRN, anime le barplot et déclenche l'alerte si besoin."""
    ser = serial.Serial(PORT, BAUDRATE, timeout=0.1)  

    fig, ax = plt.subplots()                
    stabilization_start_time = time.time()  

    snr_history = {}            
    previous_avg_sats = {}      
    anomaly_counter = 0         # Compteur d’anomalies consécutives (anti faux positifs)

    def get_sat_data(duration=1.2):
        """
        Lit des trames GSV pendant 'duration' secondes.
        Retourne :
          - sats_all     : tous les sats avec leur SNR brut {PRN: SNR}
          - sats_filtered: uniquement ceux au-dessus de SNR_MIN_THRESHOLD
        """
        start = time.time()
        sats_all, sats_filtered = {}, {}

        while time.time() - start < duration:
            try:
                # Lecture d’une ligne NMEA 
                line = ser.readline().decode('ascii', errors='replace').strip()

                # On ne traite que les GSV (infos satellites : PRN, élévation, azimut, SNR)
                if line.startswith('$') and 'GSV' in line:
                    msg = pynmea2.parse(line)

                    # Chaque GSV liste jusqu’à 4 satellites
                    for i in range(1, 5):
                        prn = getattr(msg, f'sv_prn_num_{i}', None)
                        snr = getattr(msg, f'snr_{i}', None)

                        # On garde si PRN existe et si SNR est renseigné
                        if prn and snr and snr != '':
                            snr_val = float(snr)
                            sats_all[prn] = snr_val
                            if snr_val >= SNR_MIN_THRESHOLD:
                                sats_filtered[prn] = snr_val
            except Exception:
                # Parsing ou conversion ratée : on ignore la ligne et on continue
                continue

        return sats_all, sats_filtered

    def update_snr_history(data):
        """Met à jour l'historique SNR (fenêtre glissante) pour chaque PRN présent dans 'data'."""
        for prn, snr in data.items():
            if prn not in snr_history:
                snr_history[prn] = deque(maxlen=HISTORY_LENGTH)
            snr_history[prn].append(snr)

    def get_averaged_snr():
        """Calcule le SNR moyen glissant pour chaque PRN présent dans l'historique."""
        return {p: (sum(v) / len(v)) for p, v in snr_history.items() if v}

    def compare_sat_data(prev, curr):
        """
        Compare deux états filtrés (PRN->SNR) :
          - PRNs nouveaux / PRNs disparus
        Retourne (causes, nb_prn_nouveaux)
        """
        causes = []

        # Nouveaux/disparus : sets sur les clés PRN
        new = set(curr) - set(prev)
        lost = set(prev) - set(curr)

        if len(new) >= NEW_PRNS_THRESHOLD:
            causes.append(f"{len(new)} nouveaux satellites détectés : {sorted(new)}")
        if len(lost) >= DISAPPEARED_PRNS_THRESHOLD:
            causes.append(f"{len(lost)} satellites ont disparu : {sorted(lost)}")

        # Sauts de SNR sur PRNs communs 
        snr_jumps = []
        for prn in set(curr) & set(prev):
            delta = abs(curr[prn] - prev[prn])
            if delta >= max(SNR_JUMP_THRESHOLD, 0.25 * prev[prn]):
                snr_jumps.append((prn, delta))

        if snr_jumps:
            s = ", ".join([f"{p} (Δ{d:.1f})" for p, d in snr_jumps])
            causes.append(f"Sauts de SNR détectés : {s}")

        return causes, len(new)

    def init():
        """Init de l'animation Matplotlib (axes, limites)."""
        ax.set_title("SNR satellites")
        ax.set_ylim(0, 60)  # Échelle dB-Hz standard max ~55-60
        return ax.patches

    def update(frame):
        """
        Fonction appelée périodiquement (interval=1000 ms) :
          - lit les sats (all + filtrés)
          - met à jour le barplot
          - après stabilisation, compare à l'état précédent et déclenche alerte si besoin
        """
        nonlocal previous_avg_sats, anomaly_counter

        elapsed = time.time() - stabilization_start_time
        all_sats, filtered = get_sat_data()  # Lecture courte et agrégation

        # Reset des axes et labels à chaque frame
        ax.clear()
        ax.set_ylim(0, 60)
        ax.set_xlabel("PRN")
        ax.set_ylabel("SNR (dB-Hz)")

        if all_sats:
            # Historique pour lissage (moyennes glissantes)
            update_snr_history(all_sats)

            # Données pour barplot : on affiche les SNR bruts présents
            prns = list(all_sats.keys())
            snrs = list(all_sats.values())
            bars = ax.bar(prns, snrs, color='skyblue')

            # Valeur SNR au-dessus de chaque barre (lecture rapide)
            for bar in bars:
                height = bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    height + 1,
                    f'{height:.0f}',
                    ha='center', va='bottom', fontsize=8
                )

            # SNR moyen (si tu veux l’exploiter plus tard)
            averaged = get_averaged_snr()

            # Après stabilisation + si on a un état précédent à comparer
            if elapsed > STABILIZATION_DURATION and previous_avg_sats:
                if len(filtered) < MIN_SAT_FOR_ANALYSIS:
                    # Pas assez d’infos fiables pour analyser
                    ax.set_title("Pas assez de satellites")
                    return ax.patches

                # Comparaison état précédent vs état actuel filtré
                causes, num_new = compare_sat_data(previous_avg_sats, filtered)

                # Déclenchement instantané si choc sur nb de nouveaux PRNs
                spoof_now = (num_new >= INSTANT_SHOCK_THRESHOLD)

                # Comptage d’anomalies successives (anti-bruit)
                if causes:
                    anomaly_counter += 1
                else:
                    anomaly_counter = 0

                # Alerte si anomalie persistante ou choc instantané
                if anomaly_counter >= ANOMALY_CONFIRMATION_COUNT or spoof_now:
                    print(f"\n{datetime.now().strftime('%H:%M:%S')} - SPOOFING DETECTE")
                    for cause in causes:
                        print(f"Cause : {cause}")
                    print()
                    show_alert(causes)
                    ax.set_title("SPOOFING DETECTE", color="red")
                else:
                    ax.set_title("SNR satellites")
            else:
                # Phase de chauffe/stabilisation
                ax.set_title("Stabilisation...")

            # Mémorise l’état actuel pour la prochaine comparaison
            previous_avg_sats = filtered

        return ax.patches

    # Animation Matplotlib (1 frame par seconde)
    ani = animation.FuncAnimation(fig, update, init_func=init, interval=1000)
    plt.tight_layout()
    plt.show()
    ser.close()

threading.Thread(target=worker, daemon=True).start()
root.mainloop()
