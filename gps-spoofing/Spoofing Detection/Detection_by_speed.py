# Script de détection de spoofing basé sur la vitesse calculée entre positions GGA.


import serial
import pynmea2
from geopy.distance import geodesic
from datetime import datetime
import tkinter as tk
import threading

# ------------------ CONFIGURATION ------------------
PORT = 'COM4'             
BAUDRATE = 9600            
STABILIZATION_SPEED = 5     
SPOOFING_SPEED_THRESHOLD = 5
STABILIZATION_COUNT = 5    
# ---------------------------------------------------

# --- Fenêtre principale  ---
# Création de la fenêtre Tkinter et de deux labels d'état
root = tk.Tk()
root.title(" Drone GPS Protection System")
root.geometry("900x400")
root.configure(bg="black")

label_status = tk.Label(
    root,
    text=" Initialisation du système...",
    font=("Helvetica", 20, "bold"),
    fg="white",
    bg="black"
)
label_status.pack(pady=20)

info_label = tk.Label(
    root,
    text=" En attente de données GNSS...",
    font=("Helvetica", 16),
    fg="gray",
    bg="black"
)
info_label.pack(pady=10)

# --- Variables globales ---
# Mémoires des dernières mesures et états du système
last_position = None               
last_time = None                    
fix_reported = False               

stabilized = False                 
stabilization_counter = 0           

spoofing_phase = False             
tentative_alert_shown = False       
spoofed_stabilization_counter = 0   
spoof_confirmed = False             
alert_window = None                

def close_alert_window():
    """Ferme la fenêtre d'alerte si elle existe """
    global alert_window
    if alert_window:
        alert_window.destroy()
        alert_window = None

def show_alert(message, position=None, color="orange"):
    """
    Ouvre une popup centrée à l'écran avec un message d'alerte.
    - message   : texte principal (tentative ou confirmé)
    - position  : tuple (lat, lon) facultatif, affiché si fourni
    """
    global alert_window
    close_alert_window()  

    alert_window = tk.Toplevel()
    alert_window.title("Alerte GPS")
    # Calcul des dimensions/position pour centrer la fenêtre sur l'écran
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    win_w, win_h = screen_w // 2, screen_h // 2
    pos_x, pos_y = (screen_w - win_w) // 2, (screen_h - win_h) // 2
    alert_window.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
    alert_window.configure(bg="black")
    alert_window.attributes("-topmost", True)  # Toujours au premier plan

    # Corps du message 
    text = message
    if position:
        text += f"\n {position[0]:.6f}, {position[1]:.6f}"

    # Label principal de la popup
    label = tk.Label(alert_window, text=text,
                     font=("Helvetica", 26, "bold"),
                     fg=color, bg="black", justify="center")
    label.pack(expand=True)

    # Touche Echap pour fermer rapidement la popup
    alert_window.bind("<Escape>", lambda e: close_alert_window())

def gps_reader():
    """
    Thread lecteur :
      - Ouvre le port série et lit en continu des phrases NMEA ($GNGGA/$GPGGA)
      - Parse chaque GGA avec pynmea2 pour récupérer fix_quality, latitude, longitude
      - Calcule la vitesse entre deux positions successives via geopy.distance.geodesic
      - Gère :
          * la phase de stabilisation initiale (position lente)
          * la détection de tentative (vitesse > seuil)
          * la confirmation de spoofing (re-stabilisation après tentative)
      - Met à jour l'interface Tkinter (labels + popup d'alerte)
    """
    global last_position, last_time, fix_reported
    global stabilized, stabilization_counter
    global spoofing_phase, tentative_alert_shown, spoofed_stabilization_counter
    global spoof_confirmed, alert_window

    # Ouverture du port série 
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
    except Exception as e:
        # Erreur de connexion : on affiche dans l'UI et on sort du thread
        label_status.config(text=" Erreur de connexion GPS", fg="red")
        info_label.config(text=str(e), fg="red")
        return

    # Connexion OK
    label_status.config(text=" Module GPS connecté", fg="lightgreen")

    # Boucle de lecture continue
    while True:
        try:
            # Lecture d'une ligne NMEA (chaîne ASCII)
            line = ser.readline().decode('ascii', errors='replace').strip()

            # On ne traite que les phrases GGA (info de fix + position)
            if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
                # Parsing NMEA -> objet avec attributs (gps_qual, latitude, longitude, etc.)
                msg = pynmea2.parse(line)
                fix_quality = int(msg.gps_qual)  # 0 = pas de fix, >0 = fix disponible

                # Si pas de fix : on prévient l'utilisateur et on attend
                if fix_quality == 0:
                    label_status.config(text=" Aucun signal GPS", fg="orange")
                    if not fix_reported:
                        info_label.config(text=" En attente de signal satellite...", fg="gray")
                        fix_reported = True
                    continue  # pas de calcul de vitesse ni de mise à jour de position

                # Fix valide : on réinitialise le flag d'information "pas de fix"
                fix_reported = False
                current_position = (msg.latitude, msg.longitude)  # tuple (lat, lon)
                current_time = datetime.utcnow()                  # horodatage UTC

                # Mise à jour des labels d'état
                label_status.config(text=" Signal GPS actif", fg="lightgreen")
                info_label.config(text=f" Position actuelle : {current_position[0]:.6f}, {current_position[1]:.6f}", fg="white")

                # Si on a une position précédente, on peut estimer la vitesse
                if last_position:
                    # Distance géodésique en mètres 
                    dist = geodesic(last_position, current_position).meters
                    # Temps écoulé en secondes
                    time_diff = (current_time - last_time).total_seconds()
                    # Vitesse m/s 
                    speed = dist / time_diff if time_diff > 0 else 0

                    # 1) Phase de stabilisation initiale 
                    if not stabilized:
                        if speed < STABILIZATION_SPEED:
                            stabilization_counter += 1
                            info_label.config(text=f" Stabilisation GPS... v = {speed:.1f} m/s", fg="gray")
                            if stabilization_counter >= STABILIZATION_COUNT:
                                stabilized = True
                                info_label.config(text=" Position stabilisée", fg="lightgreen")
                        else:
                            # Toujours trop rapide => on reste en attente de stabilisation
                            info_label.config(text=f" Attente stabilisation... v = {speed:.1f} m/s", fg="gray")

                    # 2) Détection de tentative : si on est stabilisé et que la vitesse franchit le seuil
                    elif not spoofing_phase and speed > SPOOFING_SPEED_THRESHOLD:
                        spoofing_phase = True
                        info_label.config(text=f" Vitesse suspecte : {speed:.1f} m/s", fg="orange")
                        label_status.config(text=" Tentative de spoofing détectée", fg="orange")
                        if not tentative_alert_shown:
                            tentative_alert_shown = True
                            # Popup d'alerte "tentative"
                            root.after(0, lambda: show_alert(" TENTATIVE DE SPOOFING DÉTECTÉE!! ⚠️", None, "orange"))

                    # 3) Confirmation : après la tentative, on attend une nouvelle stabilisation pour conclure
                    elif spoofing_phase and not spoof_confirmed:
                        if speed < STABILIZATION_SPEED:
                            spoofed_stabilization_counter += 1
                            info_label.config(text=f"🔎 Analyse spoof... v = {speed:.1f} m/s", fg="orange")
                            if spoofed_stabilization_counter >= STABILIZATION_COUNT:
                                # Spoofing confirmé : popup rouge + affichage coordonnée courante
                                spoof_confirmed = True
                                label_status.config(text="🚨 SPOOFING CONFIRMÉ", fg="red")
                                info_label.config(text=f"🚨 Position falsifiée détectée", fg="red")
                                root.after(0, lambda: show_alert("🚨 SPOOFING CONFIRMÉ 🚨", current_position, "red"))

                
                last_position = current_position
                last_time = current_time

        except Exception as e:
            info_label.config(text=f" Erreur : {e}", fg="red")


threading.Thread(target=gps_reader, daemon=True).start()
root.mainloop()  
