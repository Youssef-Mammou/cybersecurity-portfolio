import pandas as pd
import joblib
import numpy as np

# === Charger modèle et scaler ===
model = joblib.load("xgb_gnss_model.pkl")
scaler = joblib.load("xgb_scaler.pkl")

# === Charger données test ===
df_test = pd.read_csv("gnss_test_spoofed_45_2.csv")
X_test = df_test.drop(columns=["timestamp", "label"])

# === Normaliser comme à l'entraînement
X_scaled = scaler.transform(X_test)

# === Prédire les probabilités pour chaque ligne:
proba = model.predict_proba(X_scaled)  # [:,0] = normal, [:,1] = spoofed

# === Moyenne globale
mean_spoofed = np.mean(proba[:, 1]) * 100
mean_normal = np.mean(proba[:, 0]) * 100

# === Sauvegarder les probabilités ligne par ligne dans un CSV
df_test["proba_normal"] = proba[:, 0]
df_test["proba_spoofed"] = proba[:, 1]
df_test.to_csv("gnss_test_probabilities.csv", index=False)
print("\n Fichier sauvegardé : gnss_test_probabilities.csv")

print("\n Analyse globale du signal GNSS :\n")
print(f" Probabilité que le signal soit NORMAL  : {mean_normal:.2f}%")
print(f" Probabilité que le signal soit SPOOFED : {mean_spoofed:.2f}%")

if mean_spoofed > 60:
    print("\n ATTENTION : spoofing très probable !")
elif mean_spoofed > 30:
    print("\n  Spoofing possible, à surveiller.")
else:
    print("\n Signal GNSS globalement fiable.")
