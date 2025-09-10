#!/usr/bin/env python3
"""
===============================================================
 Script : U-blox vers csv.py
 Objectif : 
   Ce script enregistre directement les signaux GNSS reçus 
   par un module u-blox (via le port série) dans un fichier CSV. 
===============================================================
"""

import serial
import csv
import time
from datetime import datetime
from pyubx2 import UBXReader

# === Configuration ===
PORT = 'COM4'                         # Port série du récepteur u-blox
BAUDRATE = 9600                       # Débit de communication
OUTPUT_CSV = 'gnss_recorded_test_gps_reel.csv'  # Nom du fichier CSV de sortie
N_SAT_MAX = 12                        # Nombre maximum de satellites à enregistrer par ligne
REQUIRED_FIXES_TO_START = 4           # Nombre de fixes consécutifs nécessaires avant de commencer
REQUIRED_LOSSES_TO_STOP = 3           # Nombre de pertes consécutives avant de s’arrêter

# === Initialisation port série et UBX ===
ser = serial.Serial(PORT, BAUDRATE, timeout=1)
ubr = UBXReader(ser, protfilter=2)  # protfilter=2 => on ne lit que les messages UBX => il faut configuer le ublox pour donner les messages ubx

print(" Attente de plusieurs fixes 3D consécutifs...")

# Compteurs pour savoir quand commencer / arrêter
fix_counter = 0
loss_counter = 0
recording = False

# === Ouverture du fichier CSV de sortie ===
with open(OUTPUT_CSV, mode='w', newline='') as f:
    writer = csv.writer(f)

    # Création de l’en-tête du CSV : cn0, élévation, azimut pour chaque satellite
    headers = []
    for i in range(1, N_SAT_MAX + 1):
        headers += [f"cn0_{i}", f"elev_{i}", f"azim_{i}"]
    headers += ["timestamp", "label"]  # Ajout du temps et d’une étiquette
    writer.writerow(headers)

    # === Boucle principale ===
    while True:
        try:
            raw, msg = ubr.read()  # Lecture d’un message UBX

            # Si pas de message, on saute
            if msg is None:
                continue

            # --- Vérifier le type de fix avec NAV-PVT ---
            if msg.identity == "NAV-PVT":
                fix_type = getattr(msg, "fixType", 0)
                if fix_type == 3:  # 3D fix valide
                    fix_counter += 1
                    loss_counter = 0
                else:              # Pas de fix ou fix 2D
                    fix_counter = 0
                    loss_counter += 1

                # Démarrage de l’enregistrement si fix confirmé
                if not recording and fix_counter >= REQUIRED_FIXES_TO_START:
                    print(" Fix 3D confirmé — ENREGISTREMENT démarré.")
                    recording = True
                    continue

                # Arrêt de l’enregistrement si pertes successives
                if recording and loss_counter >= REQUIRED_LOSSES_TO_STOP:
                    print(" Fix perdu — ENREGISTREMENT arrêté.")
                    break

            # --- Si on enregistre et qu’un message NAV-SAT est reçu ---
            if recording and msg.identity == "NAV-SAT":
                sats = []
                num = getattr(msg, "numSvs", 0)  # Nombre de satellites visibles

                # Récupération des infos satellites
                for i in range(1, num + 1):
                    try:
                        cno = getattr(msg, f"cno_{i:02}")   # Puissance CN0
                        elev = getattr(msg, f"elev_{i:02}") # Élévation
                        azim = getattr(msg, f"azim_{i:02}") # Azimut
                        if cno is not None:
                            sats.append((cno, elev, azim))
                    except AttributeError:
                        continue

                # Trier les satellites par puissance décroissante
                sats_sorted = sorted(sats, key=lambda x: x[0], reverse=True)

                # Garder les N meilleurs
                sats_fixed = sats_sorted[:N_SAT_MAX]

                # Compléter avec des zéros si moins de satellites
                while len(sats_fixed) < N_SAT_MAX:
                    sats_fixed.append((0.0, 0.0, 0.0))

                # Préparer la ligne à écrire
                row = []
                for cno, elev, azim in sats_fixed:
                    row += [cno, elev, azim]
                row += [datetime.now().isoformat(), "unknown"]

                # Écriture dans le CSV
                writer.writerow(row)

        except KeyboardInterrupt:
            print(" Interruption manuelle par l’utilisateur.")
            break
        except Exception as e:
            print(f" Erreur: {e}")
            continue

# Fermeture du port série
ser.close()
print(f" Terminé. Fichier CSV sauvegardé : {OUTPUT_CSV}")
