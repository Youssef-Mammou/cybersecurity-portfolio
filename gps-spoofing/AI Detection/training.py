import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
import joblib
import os

base_dir = "E:/gps-sdr-sim/Spoofing AI 2"

# === Charger les données ===
dataset_path = os.path.join(base_dir, "Training_dataset_extended.csv")  
df = pd.read_csv(dataset_path)

# === Préparer les features et labels ===
X = df.drop(columns=["timestamp", "label"])
y = df["label"].map({"normal": 0, "spoofed": 1})

# === Normaliser les features ===
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# === Séparer les données ===
X_train, X_test, y_train, y_test = train_test_split(
    X_scaled, y, test_size=0.2, random_state=42
)

# === Entraîner le modèle XGBoost ===
model = xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss')
model.fit(X_train, y_train)

# === Évaluer la performance ===
y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)
print(f"\nAccuracy : {accuracy:.4f}")

print("\n=== Classification Report ===")
print(classification_report(y_test, y_pred))

print("=== Confusion Matrix ===")
print(confusion_matrix(y_test, y_pred))

# === Étude détaillée du modèle XGBoost ===
print("\n=== XGBoost Model Summary ===")
print("Booster type:", model.get_params()["booster"])
print("Objective function:", model.get_params()["objective"])
print("Max depth of trees:", model.get_params()["max_depth"])
print("Learning rate:", model.get_params()["learning_rate"])
print("Number of trees (estimators):", len(model.get_booster().get_dump()))
print("Number of input features:", model.n_features_in_)
booster_config = model.get_booster().save_config()
print("\n=== Actual Booster Configuration (used defaults included) ===")
print(booster_config)
# === Importances des features ===
print("\n=== Feature Importances ===")
importance = model.feature_importances_
for name, score in zip(X.columns, importance):
    print(f"{name}: {score:.4f}")

# === Nombre moyen de feuilles par arbre ===
leaves = [tree.count("leaf") for tree in model.get_booster().get_dump()]
avg_leaves = sum(leaves) / len(leaves)
print(f"\nAverage number of leaves per tree: {avg_leaves:.2f}")

# === Sauvegarder le modèle et le scaler dans le bon dossier ===
model_path = os.path.join(base_dir, "xgb_gnss_model.pkl")
scaler_path = os.path.join(base_dir, "xgb_scaler.pkl")

joblib.dump(model, model_path)
joblib.dump(scaler, scaler_path)

print(f"\nModèle sauvegardé sous : {model_path}")
print(f"Scaler sauvegardé sous : {scaler_path}")
