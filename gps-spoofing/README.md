# Internship Project: GPS Spoofing Detection & Countermeasures  
Lab-STICC, Université Bretagne Sud (CNRS), Lorient, France  
June – August 2025  

## Overview  
During this internship, I studied GNSS (GPS) spoofing attacks on drones and on my smartphone (Google Maps), reproduced them in a controlled lab environment, and designed a detection and defense framework.  

This repository contains some selected deliverables:  
- Python scripts (simplified detection modules)  
- Demo videos of spoofing detection and autonomous fallback  
- Internship report (technical documentation)  

## Contents  
- **Detection_Spoofing**  
  - `Detection_par_puissance.py` – detection by signal strength  
  - `Detection_par_vitesse.py` – detection by speed jumps  
  - `Détection_Spoofing_Satellites_et_Puissances.mp4` – demo video  
  - `Détection_Spoofing_vitesse.mp4` – demo video
  - 
- **Mode_Autonome**  
  - `detector_snr.py` – detection based on signal power  
  - `detector_speed.py` – detection based on speed anomalies  
  - `Final_Map_Project.py` – Flask + Leaflet map with real-time alerts  
  - `Basculement_En_Mode_Autonome.mp4` – demo video of autonomous fallback

- **Internship_Report.pdf**  
  Full report describing the setup, methodology, detection logic, and countermeasures studied.  

