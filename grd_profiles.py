"""Profils tarifaires GRD pour Battery Sizer.

Important :
- Les horaires HT/BT sont structurés ici pour être utilisés automatiquement par l'app.
- Les tarifs HT/BT/rachat restent modifiables dans l'interface.
- Pour les GRD où les valeurs changent selon la commune, le produit tarifaire ou l'année,
  `needs_verification=True` force un avertissement dans la sidebar.
- Mettre à jour ce fichier chaque année avec les valeurs ElCom / VESE / contrat client.
"""

from __future__ import annotations

# Format d'une plage HT : (heure_debut, heure_fin), en heures décimales.
# Exemple : (17.0, 22.0) = 17h00 à 22h00.
#
# weekend_low=True signifie : samedi/dimanche entièrement en bas tarif.
# weekend_low=False signifie : les mêmes plages HT s'appliquent aussi le week-end.

GRD_PROFILES = {
    "Groupe E": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 23.0)),
        "weekend_low": False,
        "needs_verification": False,
        "source": "Contrat utilisateur / valeurs renseignées manuellement",
        "description": (
            "HT : 07h-12h et 17h-23h. "
            "BT : 00h-07h, 12h-17h, 23h-00h. "
            "Week-end : mêmes plages sauf contrat particulier."
        ),
    },
    "Romande Energie": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((17.0, 22.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon commune / contrat Romande Energie",
        "description": (
            "HT : lundi-vendredi 17h-22h. "
            "BT : tout le reste, week-end compris."
        ),
    },
    "Yverdon Energies": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif ElCom / contrat Yverdon Energies",
        "description": (
            "Profil prérempli à vérifier. "
            "HT proposée : lundi-vendredi 07h-12h et 17h-22h. "
            "BT : reste du temps et week-end."
        ),
    },
    "SIG": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 22.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SIG / commune / produit",
        "description": "Profil indicatif : HT en journée ouvrable, BT soir/nuit/week-end.",
    },
    "Viteos": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif Viteos / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "OIKEN": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif OIKEN / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "SIL Lausanne": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 22.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SIL / produit",
        "description": "Profil indicatif : HT journée ouvrable, BT nuit/week-end.",
    },
    "SIE SA": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SIE / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "SEFA": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SEFA / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "VOenergies": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif VOénergies / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "SEIC": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SEIC / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "Gruyere Energie": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 23.0)),
        "weekend_low": False,
        "needs_verification": True,
        "source": "À vérifier selon tarif Gruyère Energie / commune / produit",
        "description": "Profil indicatif proche Groupe E, à vérifier.",
    },
    "BKW": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 20.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif BKW / commune / produit",
        "description": "Profil indicatif : HT journée ouvrable, BT nuit/week-end.",
    },
    "Personnalise": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 23.0)),
        "weekend_low": False,
        "needs_verification": False,
        "source": "Saisi manuellement",
        "description": "Définir manuellement les plages haut tarif.",
    },
}
