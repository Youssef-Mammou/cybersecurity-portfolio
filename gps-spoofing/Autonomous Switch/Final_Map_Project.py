#!/usr/bin/env python3
# - Détection de spoofing (vitesse + SNR) ; alerte visuelle + bascule en mode autonome
# - En mode autonome : suit un itinéraire OSM (A* par NetworkX) du point courant vers le point final d’un CSV (ECEF)

import os
import threading
import serial
import pynmea2
import math
import time
import pandas as pd
from collections import deque
from flask import Flask, render_template_string
from flask_socketio import SocketIO
import osmnx as ox
import networkx as nx
from shapely.geometry import LineString, Point

# Détecteurs externes (les autres codes)
from detector_speed import SpeedDetector
from detector_snr import SNRDetector

# ------------------ Configuration ------------------
PORT = 'COM4'                     # Port série du récepteur GNSS
BAUDRATE = 9600                   # Débit NMEA
MAX_SPEED_M_S = 30                # (Réservé) vitesse max utilisée ailleurs si besoin
SMOOTHING_WINDOW = 5              # Fenêtre de lissage (moyenne) sur les points "snappés"
OSM_RADIUS_METERS = 1000          # Rayon (m) pour charger le graphe routier autour de la position
MAX_DISPLAY_JUMP_METERS = 80      # Saut max autorisé entre 2 points affichés (anti-glitch)
STABILIZATION_DURATION = 30       # Délai initial avant d’autoriser une bascule autonome
start_time = time.time()          # Timestamp de démarrage du script (pour temporiser)

OUTPUT_CSV_PATH = r"E:\gps-sdr-sim\output.csv"  # Trajectoire cible (ECEF) utilisée pour générer un but autonome
AUTONOMOUS_DELAY = 1.0            # Délai (s) entre deux points simulés en mode autonome
RAYON_OSM = 3000                  # Rayon (m) pour générer l’itinéraire autonome (graphe OSM)

# Instances des détecteurs
snr_detector = SNRDetector()
speed_detector = SpeedDetector()
autonomous_mode = False        

# ------------------ Serveur Flask + Socket.IO ------------------
app = Flask(__name__)
socketio = SocketIO(app)

# --------- HTML avec double tracé (vert = GNSS, bleu = autonome) ---------
# - Deux bannières : alerte rouge (spoofing) et info bleue (mode autonome)
# - Réception d’événements 'position', 'alert', 'autonomous' via Socket.IO
html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Trajectoire GPS en temps réel</title>
    <meta charset="utf-8" />
    <style>
        #map { height: 100vh; margin: 0; padding: 0; }
        html, body { margin: 0; padding: 0; }
        .banner {
            position: fixed;
            top: 0; left: 0;
            width: 100%; z-index: 1000;
            font-size: 24px;
            text-align: center;
            padding: 10px;
            display: none;
        }
        #alertBanner { background-color: red; color: white; }
        #autoBanner { background-color: blue; color: white; top: 50px; }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
</head>
<body>
    <div id="alertBanner" class="banner">🚨 SPOOFING DÉTECTÉ !!!</div>
    <div id="autoBanner" class="banner">⚙️ BASCULEMENT EN MODE AUTONOME...</div>
    <div id="map"></div>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    <script>
        const map = L.map('map').setView([0, 0], 2);  // Vue initiale large
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 20,
        }).addTo(map);

        let path_green = [];     // Trace GNSS (réel)
        let path_blue = [];      // Trace autonome (simulé)
        let marker = null;       // Curseur position actuelle (quel que soit le mode)
        let polyline_green = null;
        let polyline_blue = null;

        const socket = io();

        // Position reçue (lat, lon, color)
        socket.on('position', data => {
            const lat = data.lat;
            const lon = data.lon;
            const color = data.color || 'green';
            const coord = [lat, lon];

            if (!marker) {
                marker = L.marker(coord).addTo(map);
                map.setView(coord, 17);
            } else {
                marker.setLatLng(coord);
            }

            if (color === 'green') {
                path_green.push(coord);
                if (polyline_green) map.removeLayer(polyline_green);
                polyline_green = L.polyline(path_green, { color: 'green' }).addTo(map);
            } else if (color === 'blue') {
                path_blue.push(coord);
                if (polyline_blue) map.removeLayer(polyline_blue);
                polyline_blue = L.polyline(path_blue, { color: 'blue' }).addTo(map);
            }
        });

        // Affiche la bannière d’alerte rouge
        socket.on('alert', () => {
            document.getElementById("alertBanner").style.display = "block";
        });

        // Affiche la bannière bleue (mode autonome)
        socket.on('autonomous', () => {
            document.getElementById("autoBanner").style.display = "block";
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(html_template)

# ------------------ Utilitaires géodésiques ------------------
def haversine(coord1, coord2):
    """Distance Haversine (mètres) entre deux (lat, lon) en degrés."""
    R = 6371000
    lat1, lon1 = map(math.radians, coord1)
    lat2, lon2 = map(math.radians, coord2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def ecef_to_latlon(x, y, z):
    """
    Conversion ECEF -> géodésique (lat, lon) approximée.
    Utilisée pour récupérer un point d'arrivée: point final (depuis CSV ECEF).
    """
    a = 6378137.0
    e = 8.1819190842622e-2
    b = math.sqrt(a**2 * (1 - e**2))
    ep = math.sqrt((a**2 - b**2) / b**2)
    p = math.sqrt(x**2 + y**2)
    th = math.atan2(a * z, b * p)
    lon = math.atan2(y, x)
    lat = math.atan2((z + ep**2 * b * math.sin(th)**3), (p - e**2 * a * math.cos(th)**3))
    return math.degrees(lat), math.degrees(lon)

# ------------------ Génération d’un itinéraire autonome OSM ------------------
def generate_autonomous_path(start_latlon):
    """
    Construit un chemin OSM (liste de (lat, lon)) :
      1) Lit OUTPUT_CSV_PATH (ECEF) et convertit le dernier point en lat/lon (destination)
      2) Charge un graphe OSM autour du milieu (start/dest)
      3) Cherche les nœuds OSM les plus proches des points start/dest
      4) Calcule le plus court chemin (poids = longueur) avec NetworkX
      5) Extrait la géométrie des arêtes et renvoie les coordonnées uniques
    """
    try:
        # CSV ECEF : colonnes "time, X, Y, Z"
        df = pd.read_csv(OUTPUT_CSV_PATH, header=None, names=["time", "X", "Y", "Z"])
        end_x, end_y, end_z = df.iloc[-1][["X", "Y", "Z"]]
        end_latlon = ecef_to_latlon(end_x, end_y, end_z)

        # Centre de téléchargement OSM 
        mid_lat = (start_latlon[0] + end_latlon[0]) / 2
        mid_lon = (start_latlon[1] + end_latlon[1]) / 2

        # Graphe OSM 
        G = ox.graph_from_point((mid_lat, mid_lon), dist=RAYON_OSM, network_type='walk')

        # Trouver les nœuds les plus proches pour départ/arrivée
        orig_node = ox.distance.nearest_nodes(G, start_latlon[1], start_latlon[0])
        dest_node = ox.distance.nearest_nodes(G, end_latlon[1], end_latlon[0])

        # Chemin le plus court ; NetworkX choisit par défaut Dijkstra
        route = nx.shortest_path(G, orig_node, dest_node, weight="length")

        # Reconstitution de la géométrie du parcours (lat, lon)
        coords = []
        for u, v in zip(route[:-1], route[1:]):
            edge_data = G.get_edge_data(u, v, 0)  # première arête (clé 0)
            geom = edge_data.get("geometry", None)
            if geom:
                coords.extend([(pt[1], pt[0]) for pt in geom.coords])
            else:
                coords.append((G.nodes[u]['y'], G.nodes[u]['x']))
                coords.append((G.nodes[v]['y'], G.nodes[v]['x']))

        # Retirer les doublons tout en conservant l’ordre
        seen = set()
        return [c for c in coords if not (c in seen or seen.add(c))]

    except Exception as e:
        print("Erreur génération itinéraire :", e)
        return []

def simulate_autonomous_movement(last_coord):
    """
      - Affiche bannière "autonomous" côté client
    """
    print(" Basculement en mode autonome...")
    socketio.emit('autonomous')
    route_coords = generate_autonomous_path(last_coord)
    print(f" Trajectoire autonome générée : {len(route_coords)} points")
    for lat, lon in route_coords:
        socketio.emit('position', {'lat': lat, 'lon': lon, 'color': 'blue'})
        time.sleep(AUTONOMOUS_DELAY)
    print(" Parcours autonome terminé.")

# ------------------ Lecture GNSS + logique de bascule ------------------
def gps_reader():
    """
    Lit le port série et :
      - Passe chaque GGA au détecteur de vitesse
      - Passe chaque GSV au détecteur SNR
      - Affiche en vert la trajectoire "snappée" sur la route (map matching simple)
      - Déclenche l'alerte + retourne la dernière coordonnée affichée pour lancer le mode autonome
    """
    global autonomous_mode
    buffer = deque(maxlen=SMOOTHING_WINDOW)  
    last_display_coord = None               
    road_network = None                   
    network_loaded = False               

    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"Connexion ouverte sur {PORT}")

        while True:
            line = ser.readline().decode('ascii', errors='replace').strip()

            # ----- GGA : position + fix -> détection de vitesse -----
            if line.startswith('$GPGGA') or line.startswith('$GNGGA'):
                status, speed, spoof = speed_detector.process(line)

                # Si spoofing confirmé par la vitesse, et délai initial dépassé -> bascule autonome
                if spoof and not autonomous_mode:
                    if time.time() - start_time > STABILIZATION_DURATION:
                        print("Spoofing confirmé par la vitesse !")
                        socketio.emit('alert')  # bannière rouge
                        autonomous_mode = True
                        return last_display_coord  

                # Map-matching + affichage en vert (trajectoire réelle)
                try:
                    msg = pynmea2.parse(line)
                    if int(msg.gps_qual) > 0:
                        lat, lon = msg.latitude, msg.longitude
                        if lat == 0 or lon == 0:
                            continue  # ignore coordonnées invalides

                        # Charger le réseau routier au premier point valide
                        if not network_loaded:
                            road_network = ox.graph_from_point((lat, lon), dist=OSM_RADIUS_METERS, network_type='walk')
                            network_loaded = True

                        # Trouver l’arête la plus proche puis projeter le point sur sa géométrie
                        nearest_edge = ox.distance.nearest_edges(road_network, lon, lat)
                        u, v, key = nearest_edge
                        edge_data = road_network.get_edge_data(u, v, key)

                        # Géométrie de l’arête (LineString) ; sinon segment simple entre nœuds
                        line_geom = edge_data['geometry'] if 'geometry' in edge_data else LineString([
                            (road_network.nodes[u]['x'], road_network.nodes[u]['y']),
                            (road_network.nodes[v]['x'], road_network.nodes[v]['y'])
                        ])

                        # Projection du point sur la ligne 
                        projected = line_geom.interpolate(line_geom.project(Point(lon, lat)))
                        snapped_coord = (projected.y, projected.x)

                        # Lissage par moyenne glissante (réduit les petits zig-zags)
                        buffer.append(snapped_coord)
                        if len(buffer) >= 2:
                            avg_lat = sum(p[0] for p in buffer) / len(buffer)
                            avg_lon = sum(p[1] for p in buffer) / len(buffer)
                            smoothed = (avg_lat, avg_lon)

                            # Anti-glitch visuel : si le saut est trop grand, on masque ce point
                            if last_display_coord:
                                dist_display = haversine(last_display_coord, smoothed)
                                if dist_display > MAX_DISPLAY_JUMP_METERS:
                                    print(f"Saut masqué à l'affichage : {dist_display:.1f} m")
                                    continue

                            # Envoi au front (trace verte)
                            socketio.emit('position', {'lat': smoothed[0], 'lon': smoothed[1], 'color': 'green'})
                            last_display_coord = smoothed

                except:
                    continue

            # ----- GSV : constellation + SNR -> détection d’anomalies SNR/PRN -----
            elif line.startswith('$GPGSV') or line.startswith('$GNGSV'):
                status, causes, spoof = snr_detector.process_gsv_for_snr(line)

                # Si spoofing confirmé par SNR/PRN, et délai initial dépassé -> bascule autonome
                if spoof and not autonomous_mode:
                    if time.time() - start_time > STABILIZATION_DURATION:
                        print("Spoofing confirmé par analyse SNR !")
                        for cause in causes:
                            print(f"Cause : {cause}")
                        socketio.emit('alert')
                        autonomous_mode = True
                        return last_display_coord 

    except Exception as e:
        print("Erreur GPS :", e)

    return last_display_coord

if __name__ == '__main__':
    def gps_thread():
        last_coord = gps_reader()
        if autonomous_mode and last_coord:
            simulate_autonomous_movement(last_coord)

    threading.Thread(target=gps_thread, daemon=True).start()
    print(" Ouvre ton navigateur sur http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000)
