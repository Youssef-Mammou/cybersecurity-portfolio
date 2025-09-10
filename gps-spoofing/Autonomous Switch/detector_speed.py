# Détecteur de spoofing basé sur la vitesse estimée entre positions successives (trames NMEA GGA).

from geopy.distance import geodesic
from datetime import datetime
import pynmea2
import time

# ------------------ Configuration ------------------
STABILIZATION_SPEED = 8         # m/s ; en phase initiale, la vitesse doit rester < à ce seuil pour considérer la position "stable"
SPOOFING_SPEED_THRESHOLD = 6    # m/s ; au-delà de ce seuil (après stabilisation), on suspecte une anomalie de vitesse
STABILIZATION_COUNT = 4         # nombre d'itérations consécutives sous STABILIZATION_SPEED pour valider la stabilisation
DISTANCE_JUMP_THRESHOLD = 30    # mètres ; on exige aussi un saut de distance minimal pour considérer l’anomalie pertinente
# ----------------------------------------------------

class SpeedDetector:
    def __init__(self):
        # Dernière position/temps validés (serviront de référence pour le calcul vitesse)
        self.last_position = None
        self.last_time = None

        # État de stabilisation initiale (avant d'activer la détection)
        self.stabilized = False
        self.stabilization_counter = 0

        # État de la séquence de spoofing 
        self.spoofing_phase = False
        self.spoofed_stabilization_counter = 0
        self.spoof_confirmed = False

    def process(self, nmea_line):
        """
        Traite une ligne NMEA (attendue : $GxGGA), met à jour l'état interne, et retourne :
          - state : "NO FIX" | "STABILIZING" | "SPEED_ANOMALY" | "SPOOFING_ANALYSIS" | "SPOOFING_CONFIRMED" | "NORMAL" | "ERROR"
          - value : vitesse calculée (float) si pertinent, sinon None ou message d'erreur
          - detected : booléen indiquant si un spoofing est confirmé
        """
        try:
            msg = pynmea2.parse(nmea_line)

            # Qualité de fix (0 = pas de fix). On ignore l'échantillon si pas de fix.
            if int(msg.gps_qual) == 0:
                return "NO FIX", None, False

            # Position courante (lat, lon) issue de la trame GGA
            current_position = (msg.latitude, msg.longitude)

            try:
                # msg.timestamp est de type datetime.time 
                current_time = datetime.combine(datetime.utcnow().date(), msg.timestamp)
                dt = (current_time - self.last_time).total_seconds() if self.last_time else 1
            except:
                current_time = time.time()
                dt = current_time - self.last_time if self.last_time else 1

            # Si on a déjà une position précédente, on peut estimer la vitesse
            if self.last_position:
                # Distance géodésique (en mètres) entre l’ancienne et la nouvelle position
                dist = geodesic(self.last_position, current_position).meters
                # Vitesse m/s ; protection dt>0 (sinon vitesse=0)
                speed = dist / dt if dt > 0 else 0

                # 1) Phase de stabilisation : on attend plusieurs échantillons "lents"
                if not self.stabilized:
                    if speed < STABILIZATION_SPEED:
                        # On incrémente le compteur si la condition de lenteur est respectée
                        self.stabilization_counter += 1
                        # Stabilisation atteinte si le compteur dépasse le seuil
                        if self.stabilization_counter >= STABILIZATION_COUNT:
                            self.stabilized = True
                            print(" Stabilisation GPS (vitesse) atteinte.")
                    # Tant que la stabilisation n'est pas finie, on reste dans cet état
                    return "STABILIZING", speed, False

                # 2) Déclenchement de la phase suspecte :
                #    on exige à la fois une vitesse élevée ET un saut de distance minimal.
                elif not self.spoofing_phase and speed > SPOOFING_SPEED_THRESHOLD and dist > DISTANCE_JUMP_THRESHOLD:
                    self.spoofing_phase = True
                    print(f" Alerte Spoofing : Anomalie de vitesse détectée : {speed:.1f} m/s sur {dist:.1f} m")
                    # On signale une anomalie de vitesse ; pas encore confirmé
                    return "SPEED_ANOMALY", speed, False

                # 3) Phase d'analyse après suspicion :
                #    On attend un retour à une faible vitesse répété pour confirmer le spoofing.
                elif self.spoofing_phase and not self.spoof_confirmed:
                    if speed < STABILIZATION_SPEED:
                        self.spoofed_stabilization_counter += 1
                        if self.spoofed_stabilization_counter >= STABILIZATION_COUNT:
                            # Spoofing confirmé après re-stabilisation
                            self.spoof_confirmed = True
                            print(" SPOOFING CONFIRMÉ par analyse de vitesse.")
                            return "SPOOFING_CONFIRMED", speed, True
                    return "SPOOFING_ANALYSIS", speed, False

            # Mise à jour des références pour la prochaine itération
            self.last_position = current_position
            self.last_time = current_time

            # Si pas de condition particulière, état normal
            return "NORMAL", None, False

        except Exception as e:
            # En cas d'erreur, on retourne un état d'erreur
            return "ERROR", str(e), False
