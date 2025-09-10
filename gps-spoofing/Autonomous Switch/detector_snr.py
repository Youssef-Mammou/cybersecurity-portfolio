# SNRDetector : détection d’anomalies GNSS en temps réel basée sur les PRN/SNR extraits des trames NMEA GSV.


import pynmea2
import time
from datetime import datetime
from collections import deque

# ---------------- Configuration ----------------
SNR_JUMP_THRESHOLD = 6              # Saut absolu minimal de SNR (dB-Hz) pour considérer une variation anormale
NEW_PRNS_THRESHOLD = 4              # Nb de PRN "nouveaux" (vs état précédent) pour signaler une anomalie
DISAPPEARED_PRNS_THRESHOLD = 4      # Nb de PRN "disparus" (vs état précédent) pour signaler une anomalie
ANOMALY_CONFIRMATION_COUNT = 2      # Nb d’itérations consécutives avec anomalies avant de conclure "SPOOFING_DETECTED"
HISTORY_LENGTH = 3                  # Taille de la fenêtre glissante pour lisser les SNR (moyenne)
INSTANT_SHOCK_THRESHOLD = 5         # Seuil pour choc immédiat (beaucoup de PRN nouveaux ET perdus en même temps)
SNR_MIN_THRESHOLD = 23              # Seuil SNR minimal pour considérer un satellite "fiable"
MIN_SAT_FOR_ANALYSIS = 4            # On n’analyse pas si moins de 4 satellites filtrés
STABILIZATION_DURATION = 60         # Délai en secondes avant d’activer l’analyse (phase de chauffe)
# ------------------------------------------------

class SNRDetector:
    def __init__(self):
        # Historique SNR par PRN : {prn: deque([snr,...], maxlen=HISTORY_LENGTH)}
        self.snr_history = {}
        # État filtré précédent (PRN -> SNR) pour comparaison d’une itération à la suivante
        self.previous_avg_sats = {}
        # Compteur d’anomalies consécutives pour éviter les faux positifs instantanés
        self.anomaly_counter = 0
        # Point de départ pour calculer la durée de stabilisation
        self.stabilization_start_time = time.time()
        # État courant mis à jour au fil des trames GSV
        self.all_sats = {}           # Tous les sats vus avec SNR (même < seuil)
        self.filtered_sats = {}      # Sats dont SNR >= SNR_MIN_THRESHOLD

    def update_snr_history(self, data):
        # Met à jour le buffer glissant de SNR pour chaque PRN présent dans 'data'
        for prn, snr in data.items():
            if prn not in self.snr_history:
                self.snr_history[prn] = deque(maxlen=HISTORY_LENGTH)
            self.snr_history[prn].append(snr)

    def get_averaged_snr(self):
        # Calcule la moyenne glissante du SNR pour chaque PRN ayant de l’historique
        return {p: sum(v)/len(v) for p, v in self.snr_history.items() if v}

    def compare_sat_data(self, prev, curr):
        # Compare deux états "filtrés" (PRN->SNR), détecte PRN nouveaux/disparus et sauts de SNR
        causes = []

        # PRN nouvellement apparus/disparus par rapport à l’itération précédente
        new = set(curr) - set(prev)
        lost = set(prev) - set(curr)

        if len(new) >= NEW_PRNS_THRESHOLD:
            causes.append(f"{len(new)} nouveaux satellites détectés : {sorted(new)}")
        if len(lost) >= DISAPPEARED_PRNS_THRESHOLD:
            causes.append(f"{len(lost)} satellites ont disparu : {sorted(lost)}")

        # Sauts de SNR : on teste un seuil absolu ET un seuil relatif (25% du SNR précédent)
        snr_jumps = []
        for prn in set(curr) & set(prev):
            delta = abs(curr[prn] - prev[prn])
            if delta >= max(SNR_JUMP_THRESHOLD, 0.25 * prev[prn]):
                snr_jumps.append((prn, delta))

        if snr_jumps:
            s = ", ".join([f"{p} (Δ{d:.1f})" for p, d in snr_jumps])
            causes.append(f"Sauts de SNR détectés : {s}")

        # Choc instantané
        spoof_now = len(new) >= INSTANT_SHOCK_THRESHOLD and len(lost) >= INSTANT_SHOCK_THRESHOLD
        if spoof_now:
            causes.append(" Changement brutal de constellation (choc immédiat)")

        return causes, spoof_now

    def process_gsv_for_snr(self, line):
      
        try:
            # On ne traite que les trames GSV (liste des satellites : PRN, SNR, etc.)
            if line.startswith('$') and 'GSV' in line:
                msg = pynmea2.parse(line)
                # Chaque GSV décrit jusqu'à 4 satellites
                for i in range(1, 5):
                    prn = getattr(msg, f'sv_prn_num_{i}', None)
                    snr = getattr(msg, f'snr_{i}', None)
                    # On conserve le PRN s’il existe et si le SNR est renseigné
                    if prn and snr and snr != '':
                        snr_val = float(snr)
                        self.all_sats[prn] = snr_val
                        if snr_val >= SNR_MIN_THRESHOLD:
                            self.filtered_sats[prn] = snr_val
        except:
            pass

        # Phase de stabilisation
        elapsed = time.time() - self.stabilization_start_time
        if elapsed < STABILIZATION_DURATION:
            return "STABILIZING", [], False

        # Pas assez de satellites fiables 
        if len(self.filtered_sats) < MIN_SAT_FOR_ANALYSIS:
            return "INSUFFICIENT_SATS", [], False

        # Mise à jour de l’historique + SNR moyen
        self.update_snr_history(self.all_sats)
        averaged = self.get_averaged_snr()

        # Si on a un état précédent, on peut comparer (détection d’anomalies)
        if self.previous_avg_sats:
            causes, spoof_now = self.compare_sat_data(self.previous_avg_sats, self.filtered_sats)

            # Anomalies présentes => incrément du compteur, sinon remise à zéro
            if causes:
                self.anomaly_counter += 1
            else:
                self.anomaly_counter = 0

            # Conclusion : anomalies répétées OU choc instantané
            if self.anomaly_counter >= ANOMALY_CONFIRMATION_COUNT or spoof_now:
                # On mémorise l’état actuel pour la continuité
                self.previous_avg_sats = self.filtered_sats.copy()
                return "SPOOFING_DETECTED", causes, True

        # Pas d’alerte : on mémorise l’état et on retourne NORMAL
        self.previous_avg_sats = self.filtered_sats.copy()
        return "NORMAL", [], False
