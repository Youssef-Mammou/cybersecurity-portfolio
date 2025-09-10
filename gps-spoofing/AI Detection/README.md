# AI-Based Spoofing Detection  

This folder contains scripts and data used for detecting GNSS spoofing with machine learning.  

- **training.py**  
  Script for training an XGBoost model on the extended dataset.  

- **test.py**  
  Script for testing the trained model on new data.  

- **training_dataset_extended.csv**  
  Dataset containing GNSS features (C/N₀, elevation, azimuth, etc.) used for training.  

- **ublox_to_csv.py**  
  Parser that converts raw u-blox GNSS data into CSV format for analysis and model input.  
