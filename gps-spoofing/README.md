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
- **Spoofing_Detection**  
  - detection_by_snr.py` – detection based on signal-to-noise ratio  
  - detection_by_speed.py` – detection based on speed jumps  
  - spoofing_detection_snr.mp4` – demo video (SNR detection)  
  - spoofing_detection_speed.mp4` – demo video (speed detection)  

- **Autonomous_Mode**  
  - detector_snr.py` – detection based on SNR (used in fallback mode)  
  - detector_speed.py` – detection based on speed anomalies (fallback mode)  
  - final_map_project.py` – Flask + Leaflet map with real-time alerts  
  - autonomous_mode_switch.mp4` – demo video of autonomous fallback  

- **Internship_Report.pdf**  
  Full report describing the setup, methodology, detection logic, and countermeasures studied.  
