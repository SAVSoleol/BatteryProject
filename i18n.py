"""French / English translations.

Two tables:
  TR: UI strings, keyed by a stable id. Use `t(lang, key, **fmt)`.
  MSG: templates for the recommend.py message *codes* (recommend emits
        (code, params) tuples so it stays language-neutral). Use `msg(lang, code, params)`.

Languages: "fr" (default) and "en". Missing keys fall back to English, then to the
raw key, so a forgotten string is visible rather than crashing.
"""

from __future__ import annotations

LANGS = {"Français": "fr", "English": "en"}

# Warning codes that should render as a hard error (red) rather than a soft warning.
ERROR_CODES = {"oversized", "no_savings", "no_healthy"}

TR: dict[str, dict[str, str]] = {
    "fr": {
        # sidebar
        "settings_header": "⚙️ Paramètres",
        "brand_label": "Marque de batterie",
        "brand_help": (
            "La marque fixe la cible de cycles sains et les sources de garantie affichées. "
            "GoodWe (matériel installé) par défaut ; Huawei = source des données compteur."
        ),
        "brand_sources_header": "📄 Specs & sources cycles",
        "brand_design_point": "Référence cycles constructeur : ~{cpy:.0f} cycles/an (voir note)",
        "brand_note_goodwe": (
            "GoodWe Lynx D (GW8.3-BAT-D-G20, module LFP de 8,32 kWh ; installation client "
            "= 4 x 8 kWh = 32 kWh) : garantie produit 10 ans, cellules certifiées ~10 000 "
            "cycles complets. La batterie est limitée par l'âge calendaire, pas par les "
            "cycles → un rythme sain de 250-350/an laisse une marge énorme (~10 000 cycles "
            "prendraient ~30-40 ans à ce rythme). Vérifiez les chiffres exacts de "
            "cycles/rétention dans le PDF de garantie officiel GoodWe."
        ),
        "brand_note_huawei": (
            "Garantie de débit Huawei LUNA2000 : 13,17 MWh / 5 kWh sur 10 ans → point de "
            "conception ~263 cycles/an (variante reste de l'UE ~329/an)."
        ),
        "tariff_import": "Tarif import (CHF/kWh)",
        "tariff_export": "Tarif export (CHF/kWh)",
        "roundtrip": "Rendement aller-retour",
        "search_range": "**Plage de recherche**",
        "cap_min": "Cap. min (kWh)",
        "cap_max": "Cap. max (kWh)",
        "p_min": "Puiss. min (kW)",
        "p_max": "Puiss. max (kW)",
        "cap_step": "Pas cap.",
        "p_step": "Pas puiss.",
        "cycles_thresh": "Seuil cycles sains / an",
        "cycles_thresh_help": (
            "La batterie recommandée est la plus grande qui reste au-dessus de ce seuil "
            "de cycles/an, c'est ce qui évite le surdimensionnement."
        ),
        "healthy_band_caption": (
            "Bande saine ≈ {low}-{high} cycles/an (LFP, ~6000 cycles garantis ≈ 20 ans)."
        ),
        "auto_update_hint": (
            "⚡ La simulation se relance automatiquement à chaque changement de paramètre, "
            "aucun bouton à presser."
        ),
        # header
        "app_caption": (
            "Dimensionnement de batterie à partir des données de compteur, optimisé par "
            "le nombre de cycles pour éviter le surdimensionnement."
        ),
        "uploader": (
            "Fichiers compteur (Huawei / Groupe E / SolarEdge, Excel ou CSV ; vous pouvez "
            "déposer les 12 fichiers mensuels Huawei d'un coup)"
        ),
        "drop_prompt": "⬆️ Déposez un ou plusieurs fichiers pour lancer l'analyse.",
        # load
        "unsupported": "Format non supporté : {e}",
        "no_data": "Aucune donnée exploitable après normalisation.",
        "spinner_load": "Lecture et normalisation des données…",
        # dataset selector (multi-file)
        "data_select_header": "Données à analyser",
        "combine_all": "Tout combiner ({n} fichiers)",
        "active_dataset": "Jeu de données actif : **{name}**",
        "files_loaded_header": "**Fichiers chargés**",
        "file_ok": "✓ {name} : {vendor}, {days} j, import {imp:,.0f} / export {exp:,.0f} kWh",
        "file_skipped": "✗ {name} : ignoré ({reason})",
        "no_valid_files": "Aucun fichier exploitable parmi ceux déposés.",
        # data quality
        "dq_expander": "📋 Qualité des données détectées",
        "dq_source": "Source détectée",
        "dq_dt": "Pas de temps",
        "dq_coverage": "Couverture",
        "dq_points": "Points",
        "unit_min": "{n} min",
        "unit_days": "{n} jours",
        "dq_totals": (
            "**Import total** : {imp:,.0f} kWh, **Export (surplus) total** : {exp:,.0f} kWh"
        ),
        "dq_partial": "Données < 1 an : les cycles/an sont annualisés et peuvent être biaisés.",
        "dq_no_surplus": "Pas de surplus solaire → une batterie n'a aucun intérêt ici.",
        # simulate
        "empty_range": "Plage de recherche vide, vérifiez min/max/pas.",
        "spinner_sim": "Simulation de {n} combinaisons…",
        # KPI
        "recommendation": "Recommandation",
        "kpi_capacity": "Capacité",
        "kpi_power": "Puissance",
        "kpi_savings": "Économies",
        "kpi_cycles": "Cycles",
        "kpi_surplus": "Surplus capté",
        "per_year": "{v}/an",
        "savings_unit": "{v} CHF/an",
        "delta_vs_max": "{v} vs gain-max",
        "compare_caption": (
            "Comparaison, choix **gain max** : **{cap} kWh / {power} kW** → {gain} CHF/an "
            "mais seulement **{cyc} cycles/an** (surdimensionné)."
        ),
        "why_cycles_header": "❓ Pourquoi les cycles ? Pourquoi {low} cycles/an ?",
        "why_cycles_body": (
            "**Un cycle = une charge + décharge complète.** Les cycles/an mesurent si la "
            "capacité achetée est vraiment utilisée, c'est le compteur d'utilisation honnête.\n\n"
            "- Une **petite** batterie se remplit et se vide presque chaque jour : chaque kWh travaille.\n"
            "- Une batterie **trop grande** reste à moitié pleine : vous payez une capacité qui dort.\n\n"
            "C'est le même fait physique que la courbe qui s'aplatit, vu côté batterie au lieu "
            "du côté argent. Une grande batterie affiche un gain total plus élevé, mais son faible "
            "nombre de cycles trahit la capacité inutilisée.\n\n"
            "**La bande saine {low}-{high} cycles/an** cycle assez fort pour justifier son coût, "
            "sans s'user avant la garantie (cellules LFP ~6000 cycles, donc ~{low}/an ≈ 20 ans). "
            "En dessous de {low}/an, la capacité est surdimensionnée.\n\n"
            "**La règle :** d'abord écarter toute taille sous {low}/an (les options inutilisées, "
            "surdimensionnées), puis parmi le reste prendre le plus gros gain. On obtient la plus "
            "grande batterie encore vraiment utilisée, donc le chiffre du gain ne peut plus mentir."
        ),
        # charts
        "tab_front": "📈 Gain vs capacité",
        "tab_soc": "🔋 État de charge",
        "tab_cyc": "♻️ Cycles cumulés",
        "tab_ba": "📊 Avant / Après",
        "healthy_band": "bande saine",
        "legend_gain": "Gain (CHF/an)",
        "legend_cycles": "Cycles/an",
        "legend_recommended": "Recommandé",
        "legend_maxgain": "Gain max",
        "axis_capacity": "Capacité (kWh)",
        "axis_gain": "Gain (CHF/an)",
        "axis_cycles": "Cycles/an",
        "col_pct_max": "% du gain max",
        "axis_soc": "SOC (%)",
        "axis_date": "Date",
        "soc_title": "État de charge, {cap} kWh / {power} kW",
        "cyc_legend_cum": "Cycles cumulés",
        "cyc_legend_steady": "rythme constant (idéal)",
        "cyc_axis": "Cycles équivalents cumulés",
        "cyc_title": (
            "Cycles cumulés, une droite = batterie utilisée régulièrement (bien dimensionnée)"
        ),
        "ba_import_before": "Import avant",
        "ba_import_after": "Import après",
        "ba_export_before": "Export avant",
        "ba_export_after": "Export après",
        "ba_axis": "kWh / mois",
        # battery cost inputs (payback tab)
        "costs_header": "Coûts batterie (rentabilité)",
        "cost_price_lo": "Prix bas (CHF/kWh)",
        "cost_price_hi": "Prix haut (CHF/kWh)",
        "cost_fixed": "Coût fixe installation (CHF)",
        "cost_fixed_help": (
            "Onduleur hybride, BMS, câblage, main-d'œuvre, payé avant le 1er kWh. "
            "Mettez 0 si un onduleur compatible batterie existe déjà."
        ),
        "cost_life": "Durée de vie batterie (ans)",
        # payback tab
        "tab_pay": "Rentabilité",
        "pay_earns_title": "Ce que chaque kWh ajouté RAPPORTE vs ce qu'il COÛTE à posséder",
        "pay_earns_axis": "CHF/an gagnés par ce kWh",
        "pay_nth_axis": "le N-ième kWh de capacité",
        "pay_own_band": "coûte à posséder 1 kWh/an ({lo:.0f}-{hi:.0f} CHF)",
        "pay_kpi_rec": "Taille recommandée",
        "pay_kpi_payback": "Rentabilité à cette taille",
        "pay_kpi_best": "Taille la plus rentable",
        "pay_yr_val": "{v} ans",
        "pay_verdict": (
            "Recommandé : **{rec} kWh**, la plus grande batterie encore pleinement cyclée "
            "(~{cyc} cycles/an). Elle capte le maximum d'économies sans payer de capacité qui "
            "dort. (Aux prix actuels le retour est long : une batterie est ici un choix "
            "d'autoconsommation, pas un gain rapide.)"
        ),
        "pay_health_title": "Économies selon la taille, prendre la plus haute barre **VERTE** (la plus grande encore pleinement cyclée)",
        "pay_health_caption": (
            "Vert = cycle encore ≥ {low}/an (chaque kWh est utilisé). Gris = surdimensionné "
            "(sous {low}/an, capacité qui dort). Les économies montent toujours avec la taille, "
            "mais au-delà du vert vous payez de la capacité inutilisée : le meilleur achat est "
            "donc la plus haute barre verte."
        ),
        "pay_rec_star": "★ {cap} kWh",
        "pay_oversized_note": "surdimensionné : capacité inutilisée",
        "pay_legend_healthy": "pleinement cyclée (saine)",
        "pay_legend_oversized": "surdimensionnée (capacité qui dort)",
        "pay_earns_caption": (
            "Chaque barre = ce que rapporte le **kWh suivant** par an ; la bande grise = ce "
            "qu'un kWh **coûte à posséder** par an. Règle d'arrêt : ajouter des kWh tant que "
            "les barres atteignent la bande, s'arrêter quand elles passent nettement en dessous "
            "(vert = clairement rentable · orange = à l'équilibre · rouge = coûte plus qu'il ne "
            "rapporte). Le 1er kWh rapporte en général le plus, c'est la courbe qui s'aplatit, "
            "pas une raison de n'acheter qu'1 kWh."
        ),
        "pay_status_green": (
            "À vos prix, la taille recommandée **{rec} kWh** rapporte encore plus qu'elle ne "
            "coûte (vert) : la vue monétaire et le choix par cycles concordent."
        ),
        "pay_status_amber": (
            "À vos prix, la taille recommandée **{rec} kWh** est à l'équilibre (orange) : "
            "monétaire et choix par cycles concordent à peu près."
        ),
        "pay_status_red": (
            "À vos prix, la taille recommandée **{rec} kWh** coûte déjà plus par kWh qu'elle ne "
            "rapporte (rouge). Elle est dimensionnée pour un **cyclage sain, pas pour la "
            "rentabilité** : si l'argent prime, réduire vers **{pb} kWh** (le creux de "
            "rentabilité) ou la dernière barre verte."
        ),
        "pay_rec_line": "Recommandé : {cap} kWh",
        "pay_rec_caption": (
            "La barre verte la plus haute est le **1er kWh**, pas le meilleur achat. "
            "La ligne verticale marque la taille **recommandée ({cap} kWh)** : la plus "
            "grande qui reste dans la bande de cycles saine."
        ),
        "pay_pb_title": "Rentabilité système (coût fixe + modules), en U : 1 kWh et 20 kWh perdent",
        "pay_pb_axis": "Retour sur investissement (ans)",
        "pay_life_line": "durée de vie ~{life:.0f} ans, au-dessus = jamais rentabilisé",
        "pay_best_label": "moins mauvais",
        "pay_pb_caption": (
            "Le coût fixe d'installation se répartit sur la capacité, d'où un U : trop petit "
            "gaspille les frais fixes, trop grand porte de la capacité inutilisée. Le creux "
            "**{pb} kWh** est la taille au meilleur retour. Le choix affiché **{rec} kWh** est "
            "décidé sur les cycles (sans prix) ; s'ils diffèrent, **{pb} kWh** est le choix "
            "monétaire et **{rec} kWh** le mieux cyclé : choisir selon ce que le client privilégie."
        ),
        # four-lens payback charts (ported from battery_sizing_explained.ipynb)
        "pay_curve_marg": "le N-ième kWh rapporte",
        "pay_curve_total": "gain total (CHF/an)",
        "pay_curve_y_marg": "CHF/an par kWh ajouté",
        "pay_curve_y_total": "gain total (CHF/an)",
        "pay_curve_caption": (
            "Les économies totales montent toujours, mais chaque kWh ajouté rapporte moins que "
            "le précédent (barres qui rétrécissent). La courbe s'aplatit car une batterie se "
            "remplit de bas en haut, le 1er kWh capte le surplus de chaque jour, le dernier "
            "seulement les rares gros jours. **Gain max** surdimensionne car il chasse cette "
            "queue plate."
        ),
        "pay_cycles_use": "cycles/an (usage)",
        "pay_cycles_frac": "capacité cyclée par jour",
        "pay_cycles_healthy": "sain {low}-{high}",
        "pay_cycles_oversized": "surdimensionné < 150",
        "pay_cycles_y2": "fraction de capacité utilisée par jour",
        "pay_cycles_caption": (
            "Les cycles/an mesurent l'intensité d'usage de chaque kWh. Au-dessus de {low} = "
            "chaque kWh utilisé quotidiennement (bande verte) ; sous 150 = capacité inactive "
            "(surdimensionné). La taille recommandée est la plus grande qui reste dans le vert "
            ", un indicateur sans prix de **bien utilisée**."
        ),
        # The reason we don't pick the payback low-point depends on which side of the
        # recommendation it sits: smaller => harder-cycled but leaves savings on the table;
        # larger => under-cycled (oversized); same capacity => the two views agree.
        "pay_best_annot_undersized": "moins mauvais (optimum monétaire)<br>{cap} kWh · {pb} an<br>mais ~{gap} CHF/an de moins<br>que {rec} kWh, encore bien cyclé →<br>pourquoi on agrandit",
        "pay_best_annot_oversized": "moins mauvais (optimum monétaire)<br>{cap} kWh · {pb} an<br>mais {cyc} cycles/an &lt; {low} :<br>capacité sous-utilisée →<br>pourquoi on ne choisit pas ça",
        "pay_best_annot_agree": "optimum monétaire = recommandé<br>{cap} kWh · {pb} an<br>retour et cycles concordent ici",
        "pay_rec_annot": "recommandé : {cap} kWh (sain en cycles)",
        "pay_pb_hover": "{cap} kWh → retour {pb} an",
        "pay_cycles_hover": "{cap} kWh · {cyc} cycles/an",
        "pay_cycles_hover2": "{cap} kWh · {frac}× capacité/jour",
        # PDF
        "pdf_sections_header": "📄 Sections du rapport PDF",
        "pdf_sections_label": "Graphiques à inclure",
        "pdf_sections_hint": "Choisir les graphiques à envoyer au client ; le tableau de synthèse est toujours inclus.",
        "pdf_sections_empty": "Aucun graphique sélectionné, le PDF ne contiendra que le tableau de synthèse.",
        "pdf_button": "⬇️ Télécharger le rapport PDF",
        "pdf_filename": "bilan_batterie.pdf",
        "pdf_title": "Dimensionnement Batterie",
        "pdf_section": "Batterie recommandee",
        "pdf_brand": "Marque batterie",
        "pdf_capacity": "Capacite",
        "pdf_power": "Puissance",
        "pdf_savings": "Economies",
        "pdf_cycles": "Cycles",
        "pdf_cycles_val": "{cyc} /an (sain: {low}-{high})",
        "pdf_import_avoided": "Import evite",
        "pdf_energy_val": "{kwh} kWh/an ({pct})",
        "pdf_surplus": "Surplus capte",
        "pdf_compare": "Comparaison gain max",
        "pdf_compare_val": "{cap} kWh -> {gain} CHF/an, {cyc} cycles/an",
        "pdf_source": "Source / couverture",
        "pdf_source_val": "{vendor} / {days} j",
        "pdf_savings_val": "{v} CHF/an",
        "pdf_fig1_xlabel": "Capacité (kWh)",
        "pdf_fig1_ylabel": "Gain (CHF/an)",
        "pdf_fig1_y2label": "Cycles/an",
        "pdf_fig1_title": "Gain et cycles selon la capacité",
        "pdf_fig2_title": "Avant / Après",
        "pdf_fig2_ylabel": "kWh/mois",
        "pdf_cycles_title": "Cycles par an selon la capacité, chaque kWh est-il vraiment utilisé ?",
        # PDF chart captions (pour qu'un acheteur lise le raisonnement, pas seulement les graphiques)
        "pdf_cap_frontier": (
            "Les économies (bleu) montent avec la capacité tandis que les cycles par an (vert) "
            "baissent. La taille marquée est la recommandation, la plus grande batterie encore "
            "dans la bande de cycles saine ; le choix gain max plus à droite achète de la "
            "capacité qui reste inactive."
        ),
        "pdf_cap_soc": (
            "Niveau de charge de la batterie sur la période. De pleines variations quotidiennes "
            "signifient une capacité réellement utilisée ; de longs plateaux près du plein ou du "
            "vide signifient une capacité inactive."
        ),
        "pdf_cap_cyc": (
            "Cycles complets équivalents cumulés. Une courbe qui suit la référence grise droite "
            "signifie une batterie cyclée régulièrement, signe d'un bon dimensionnement."
        ),
        "pdf_cap_ba": (
            "Import et export réseau mensuels, avant et après la batterie. La baisse d'import "
            "est l'économie sur la facture ; la baisse d'export est le surplus désormais stocké "
            "sur place au lieu d'être revendu à bas prix."
        ),
    },
    "en": {
        # sidebar
        "settings_header": "⚙️ Settings",
        "brand_label": "Battery brand",
        "brand_help": (
            "The brand sets the healthy-cycle target and the warranty sources shown. "
            "GoodWe (installed hardware) is the default; Huawei = the meter-data source."
        ),
        "brand_sources_header": "📄 Cycle specs & sources",
        "brand_design_point": "Mfr. cycle reference: ~{cpy:.0f} cycles/yr (see note)",
        "brand_note_goodwe": (
            "GoodWe Lynx D (GW8.3-BAT-D-G20, 8.32 kWh LFP module; client install = 4 x 8 "
            "kWh = 32 kWh): 10-yr product warranty, cells rated ~10,000 full cycles. The "
            "battery is calendar-limited, not cycle-limited → a healthy 250-350/yr leaves "
            "huge headroom (~10,000 cycles would take ~30-40 yr at that rate). Verify the "
            "exact warranty cycle/retention figures against GoodWe's official PDF."
        ),
        "brand_note_huawei": (
            "Huawei LUNA2000 throughput warranty: 13.17 MWh / 5 kWh over 10 yr → ~263 "
            "cycles/yr design point (rest-of-EU variant ~329/yr)."
        ),
        "tariff_import": "Import tariff (CHF/kWh)",
        "tariff_export": "Export tariff (CHF/kWh)",
        "roundtrip": "Round-trip efficiency",
        "search_range": "**Search range**",
        "cap_min": "Min cap. (kWh)",
        "cap_max": "Max cap. (kWh)",
        "p_min": "Min power (kW)",
        "p_max": "Max power (kW)",
        "cap_step": "Cap. step",
        "p_step": "Power step",
        "cycles_thresh": "Healthy cycles/yr threshold",
        "cycles_thresh_help": (
            "The recommended battery is the largest one that stays above this cycles/yr "
            "threshold, that's what prevents oversizing."
        ),
        "healthy_band_caption": (
            "Healthy band ≈ {low}-{high} cycles/yr (LFP, ~6000 warranted cycles ≈ 20 years)."
        ),
        "auto_update_hint": (
            "⚡ The simulation re-runs automatically whenever you change a parameter, "
            "no button to press."
        ),
        # header
        "app_caption": (
            "Battery sizing from meter data, optimized by cycle count to avoid oversizing."
        ),
        "uploader": (
            "Meter files (Huawei / Groupe E / SolarEdge, Excel or CSV; you can drop all 12 "
            "monthly Huawei files at once)"
        ),
        "drop_prompt": "⬆️ Drop one or more files to start the analysis.",
        # load
        "unsupported": "Unsupported format: {e}",
        "no_data": "No usable data after normalization.",
        "spinner_load": "Reading and normalizing data…",
        # dataset selector (multi-file)
        "data_select_header": "Data to analyze",
        "combine_all": "Combine all ({n} files)",
        "active_dataset": "Active dataset: **{name}**",
        "files_loaded_header": "**Loaded files**",
        "file_ok": "✓ {name}: {vendor}, {days} d, import {imp:,.0f} / export {exp:,.0f} kWh",
        "file_skipped": "✗ {name}: skipped ({reason})",
        "no_valid_files": "None of the dropped files are usable.",
        # data quality
        "dq_expander": "📋 Detected data quality",
        "dq_source": "Detected source",
        "dq_dt": "Time step",
        "dq_coverage": "Coverage",
        "dq_points": "Points",
        "unit_min": "{n} min",
        "unit_days": "{n} days",
        "dq_totals": (
            "**Total import**: {imp:,.0f} kWh, **Total export (surplus)**: {exp:,.0f} kWh"
        ),
        "dq_partial": "Less than 1 year of data: cycles/yr are annualized and may be biased.",
        "dq_no_surplus": "No solar surplus → a battery brings no benefit here.",
        # simulate
        "empty_range": "Empty search range, check min/max/step.",
        "spinner_sim": "Simulating {n} combinations…",
        # KPI
        "recommendation": "Recommendation",
        "kpi_capacity": "Capacity",
        "kpi_power": "Power",
        "kpi_savings": "Savings",
        "kpi_cycles": "Cycles",
        "kpi_surplus": "Surplus captured",
        "per_year": "{v}/yr",
        "savings_unit": "{v} CHF/yr",
        "delta_vs_max": "{v} vs max-gain",
        "compare_caption": (
            "Comparison, **max-gain** pick: **{cap} kWh / {power} kW** → {gain} CHF/yr "
            "but only **{cyc} cycles/yr** (oversized)."
        ),
        "why_cycles_header": "❓ Why cycles? Why {low} cycles/yr?",
        "why_cycles_body": (
            "**A cycle = one full charge + discharge.** Cycles/year is the honest utilization "
            "meter: it tells you whether the capacity you bought is actually being used.\n\n"
            "- A **small** battery fills and empties almost daily: every kWh is working.\n"
            "- A **too-large** battery sits mostly half-full, rarely fully used: you paid for "
            "capacity that loafs.\n\n"
            "It is the same physical fact as the flattening gain curve, just measured from the "
            "battery's side instead of the money's side. A big battery looks better on total gain, "
            "but its low cycle count exposes that the extra capacity is idle.\n\n"
            "**The healthy band {low}-{high} cycles/yr** cycles hard enough to justify its cost, "
            "but not so hard it wears out before the warranty (LFP cells last ~6000 cycles, so "
            "~{low}/yr is about 20 years). Below {low}/yr the capacity is oversized.\n\n"
            "**The rule:** first throw out every size cycling below {low}/yr (the idle, oversized "
            "options), then among what's left pick the biggest gain. That lands on the largest "
            "battery still genuinely worked, so the money number can't lie to you."
        ),
        # charts
        "tab_front": "📈 Gain vs capacity",
        "tab_soc": "🔋 State of charge",
        "tab_cyc": "♻️ Cumulative cycles",
        "tab_ba": "📊 Before / After",
        "healthy_band": "healthy band",
        "legend_gain": "Gain (CHF/yr)",
        "legend_cycles": "Cycles/yr",
        "legend_recommended": "Recommended",
        "legend_maxgain": "Max gain",
        "axis_capacity": "Capacity (kWh)",
        "axis_gain": "Gain (CHF/yr)",
        "axis_cycles": "Cycles/yr",
        "col_pct_max": "% of max gain",
        "axis_soc": "SOC (%)",
        "axis_date": "Date",
        "soc_title": "State of charge, {cap} kWh / {power} kW",
        "cyc_legend_cum": "Cumulative cycles",
        "cyc_legend_steady": "steady pace (ideal)",
        "cyc_axis": "Cumulative equivalent cycles",
        "cyc_title": (
            "Cumulative cycles, a straight line = battery used regularly (well sized)"
        ),
        "ba_import_before": "Import before",
        "ba_import_after": "Import after",
        "ba_export_before": "Export before",
        "ba_export_after": "Export after",
        "ba_axis": "kWh / month",
        # battery cost inputs (payback tab)
        "costs_header": "Battery costs (payback)",
        "cost_price_lo": "Low price (CHF/kWh)",
        "cost_price_hi": "High price (CHF/kWh)",
        "cost_fixed": "Fixed install cost (CHF)",
        "cost_fixed_help": (
            "Hybrid inverter, BMS, wiring, labour, paid before the 1st kWh. "
            "Set 0 if a battery-ready inverter already exists."
        ),
        "cost_life": "Battery life (years)",
        # payback tab
        "tab_pay": "Payback",
        "pay_earns_title": "What each added kWh EARNS vs what it COSTS to own",
        "pay_earns_axis": "CHF/yr earned by that kWh",
        "pay_nth_axis": "the Nth kWh of capacity",
        "pay_own_band": "costs to own 1 kWh/yr ({lo:.0f}-{hi:.0f} CHF)",
        "pay_kpi_rec": "Recommended size",
        "pay_kpi_payback": "Payback at this size",
        "pay_kpi_best": "Best-money size",
        "pay_yr_val": "{v} yr",
        "pay_verdict": (
            "Recommended: **{rec} kWh**, the largest battery still fully cycled (~{cyc} "
            "cyc/yr). It captures the most savings without paying for capacity that sits idle. "
            "(At today's prices payback is long; a battery here is a self-consumption choice, "
            "not a quick return.)"
        ),
        "pay_health_title": "Savings by battery size, pick the tallest **GREEN** bar (the biggest one still fully cycled)",
        "pay_health_caption": (
            "Green = still cycles ≥ {low}/yr (every kWh gets used). Gray = oversized (below "
            "{low}/yr, capacity sits idle). Savings keep rising with size, but past the green "
            "zone you pay for idle capacity, so the best buy is the tallest green bar."
        ),
        "pay_rec_star": "★ {cap} kWh",
        "pay_oversized_note": "oversized: idle capacity",
        "pay_legend_healthy": "fully cycled (healthy)",
        "pay_legend_oversized": "oversized (idle capacity)",
        "pay_earns_caption": (
            "Each bar = what the **next** kWh of capacity earns per year; the grey band = what "
            "a kWh **costs to own** per year. Stop rule: add kWh while bars reach the band, stop "
            "once they fall clearly below it (green = comfortably worth it · amber = about "
            "breaks even · red = costs more than it earns). The 1st kWh usually earns the most, "
            "that's the curve flattening, not a reason to buy only 1 kWh."
        ),
        "pay_status_green": (
            "At your prices the recommended **{rec} kWh** still earns more than it costs "
            "(green): the money view and the cycle-based pick agree."
        ),
        "pay_status_amber": (
            "At your prices the recommended **{rec} kWh** about breaks even (amber): money and "
            "the cycle-based pick roughly agree."
        ),
        "pay_status_red": (
            "At your prices the recommended **{rec} kWh** already costs more per kWh than it "
            "earns (red). It's sized for **healthy cycling, not payback**: if money is the "
            "priority, size down toward **{pb} kWh** (the payback low-point) or the last green bar."
        ),
        "pay_rec_line": "Recommended: {cap} kWh",
        "pay_rec_caption": (
            "The tallest green bar is the **1st kWh**, not the best buy. The vertical line "
            "marks the **recommended size ({cap} kWh)**: the largest one still inside the "
            "healthy cycle band."
        ),
        "pay_pb_title": "Whole-system payback (fixed install + modules), U-shaped: 1 kWh and 20 kWh both lose",
        "pay_pb_axis": "Payback (years)",
        "pay_life_line": "battery life ~{life:.0f} yr, above = never pays back",
        "pay_best_label": "least-bad",
        "pay_pb_caption": (
            "Fixed install cost spreads over capacity, so payback is U-shaped: too small wastes "
            "the flat fee, too big carries idle capacity. The low-point **{pb} kWh** is the "
            "cheapest-payback size. The headline **{rec} kWh** is chosen on cycles (price-free); "
            "when the two differ, **{pb} kWh** is the money choice and **{rec} kWh** the "
            "more-fully-cycled one, pick by what the client values."
        ),
        # four-lens payback charts (ported from battery_sizing_explained.ipynb)
        "pay_curve_marg": "the Nth kWh earns",
        "pay_curve_total": "total gain (CHF/yr)",
        "pay_curve_y_marg": "marginal CHF/yr per added kWh",
        "pay_curve_y_total": "total gain (CHF/yr)",
        "pay_curve_caption": (
            "Total savings keep rising, but each added kWh earns less than the one before "
            "(bars shrink). The curve flattens because a battery fills from the bottom up, "
            "the first kWh catches every day's surplus, the last only the rare big day. "
            "**Biggest gain** oversizes because it chases that flat tail."
        ),
        "pay_cycles_use": "cycles/yr (use)",
        "pay_cycles_frac": "capacity cycled per day",
        "pay_cycles_healthy": "healthy {low}-{high}",
        "pay_cycles_oversized": "oversized < 150",
        "pay_cycles_y2": "fraction of capacity used per day",
        "pay_cycles_caption": (
            "Cycles/yr = how hard each kWh works. Above {low} = every kWh used daily (green "
            "band); below 150 = capacity sits idle (oversized). The recommended size is the "
            "largest that stays in the green, a price-free proxy for **well-used**."
        ),
        # The reason we don't pick the payback low-point depends on which side of the
        # recommendation it sits: smaller => harder-cycled but leaves savings on the table;
        # larger => under-cycled (oversized); same capacity => the two views agree.
        "pay_best_annot_undersized": "least-bad (money optimum)<br>{cap} kWh · {pb} yr<br>but earns ~{gap} CHF/yr less<br>than {rec} kWh, still well-cycled →<br>why we size up from here",
        "pay_best_annot_oversized": "least-bad (money optimum)<br>{cap} kWh · {pb} yr<br>but {cyc} cycles/yr &lt; {low}:<br>capacity under-used →<br>why we don't pick this",
        "pay_best_annot_agree": "money optimum = recommended<br>{cap} kWh · {pb} yr<br>payback and cycles agree here",
        "pay_rec_annot": "recommended: {cap} kWh (cycles-healthy)",
        "pay_pb_hover": "{cap} kWh → payback {pb} yr",
        "pay_cycles_hover": "{cap} kWh · {cyc} cycles/yr",
        "pay_cycles_hover2": "{cap} kWh · {frac}× capacity/day",
        # PDF
        "pdf_sections_header": "📄 PDF report sections",
        "pdf_sections_label": "Charts to include",
        "pdf_sections_hint": "Pick the charts to send the client; the summary table is always included.",
        "pdf_sections_empty": "No charts selected, the PDF will contain only the summary table.",
        "pdf_button": "⬇️ Download PDF report",
        "pdf_filename": "battery_report.pdf",
        "pdf_title": "Battery Sizing",
        "pdf_section": "Recommended battery",
        "pdf_brand": "Battery brand",
        "pdf_capacity": "Capacity",
        "pdf_power": "Power",
        "pdf_savings": "Savings",
        "pdf_cycles": "Cycles",
        "pdf_cycles_val": "{cyc} /yr (healthy: {low}-{high})",
        "pdf_import_avoided": "Import avoided",
        "pdf_energy_val": "{kwh} kWh/yr ({pct})",
        "pdf_surplus": "Surplus captured",
        "pdf_compare": "Max-gain comparison",
        "pdf_compare_val": "{cap} kWh -> {gain} CHF/yr, {cyc} cycles/yr",
        "pdf_source": "Source / coverage",
        "pdf_source_val": "{vendor} / {days} d",
        "pdf_savings_val": "{v} CHF/yr",
        "pdf_fig1_xlabel": "Capacity (kWh)",
        "pdf_fig1_ylabel": "Gain (CHF/yr)",
        "pdf_fig1_y2label": "Cycles/yr",
        "pdf_fig1_title": "Gain and cycles by capacity",
        "pdf_fig2_title": "Before / After",
        "pdf_fig2_ylabel": "kWh/month",
        "pdf_cycles_title": "Cycles per year by capacity, is every kWh actually used?",
        # PDF chart captions (so a buyer reads the reasoning, not just the charts)
        "pdf_cap_frontier": (
            "Savings (blue) keep rising with capacity while cycles per year (green) fall. The "
            "marked size is the recommendation, the largest battery still inside the healthy "
            "cycle band; the max-gain pick further right buys capacity that sits idle."
        ),
        "pdf_cap_soc": (
            "Battery charge level across the period. Full daily swings mean the capacity is "
            "genuinely used; long flat stretches near full or empty mean idle capacity."
        ),
        "pdf_cap_cyc": (
            "Cumulative equivalent full cycles. A line that tracks the straight grey reference "
            "means the battery is cycled steadily, a sign it is well sized."
        ),
        "pdf_cap_ba": (
            "Monthly grid import and export, before and after the battery. The drop in import "
            "is the bill saving; the drop in export is surplus now stored on site instead of "
            "sold cheaply."
        ),
    },
}

# Templates for recommend.py message codes. {params} match the dicts recommend emits.
MSG: dict[str, dict[str, str]] = {
    "fr": {
        "cycles_first": (
            "Choix orienté cycles : la plus grande batterie qui reste ≥ {cycles_low:.0f} "
            "cycles/an, capte le plus de valeur sans surdimensionner."
        ),
        "smaller_than_max": (
            "{saved:.0f} kWh de moins que le choix gain-max ({max_cap:.0f} kWh), "
            "pour {pct:.0%} du gain."
        ),
        "no_healthy": (
            "Aucune taille de la plage n'atteint {cycles_low:.0f} cycles/an à ce niveau de "
            "surplus, affichage de l'option la mieux utilisée ({cyc:.0f} cycles/an). "
            "Une batterie peut être difficile à justifier pour ce client."
        ),
        "just_below": (
            "{cyc:.0f} cycles/an, juste sous la bande idéale {low:.0f}-{high:.0f} ; "
            "acceptable, légèrement grand."
        ),
        "within_band": "{cyc:.0f} cycles/an, dans la bande saine {low:.0f}-{high:.0f}.",
        "above_band": (
            "{cyc:.0f} cycles/an, au-dessus de {high:.0f} ; bien utilisée, mais à vérifier "
            "contre le débit garanti de la batterie."
        ),
        "oversized": (
            "⚠️ Surdimensionnée : seulement {cyc:.0f} cycles/an (sain : {low:.0f}-{high:.0f}). "
            "La batterie se remplit rarement, capacité probablement surpayée."
        ),
        "no_savings": (
            "Économies estimées ~0, peu de surplus à stocker ; batterie non rentable."
        ),
        "partial_year": (
            "Les données ne couvrent que {days:.0f} jours, les cycles/an sont annualisés et "
            "peuvent être biaisés (plus de cycles en été qu'en hiver). Préférez une année "
            "complète."
        ),
    },
    "en": {
        "cycles_first": (
            "Cycles-first pick: the largest battery that still stays ≥ {cycles_low:.0f} "
            "cycles/yr, captures the most value without oversizing."
        ),
        "smaller_than_max": (
            "{saved:.0f} kWh smaller than the max-gain pick ({max_cap:.0f} kWh), "
            "for {pct:.0%} of the gain."
        ),
        "no_healthy": (
            "No size in range reaches {cycles_low:.0f} cycles/yr at this surplus level, "
            "showing the best-utilized option ({cyc:.0f} cycles/yr). A battery may be hard to "
            "justify for this client."
        ),
        "just_below": (
            "{cyc:.0f} cycles/yr, just below the {low:.0f}-{high:.0f} ideal band; "
            "acceptable, leans slightly large."
        ),
        "within_band": "{cyc:.0f} cycles/yr, within the healthy {low:.0f}-{high:.0f} band.",
        "above_band": (
            "{cyc:.0f} cycles/yr, above {high:.0f}; well used, but verify it against the "
            "battery's warranted throughput."
        ),
        "oversized": (
            "⚠️ Oversized: only {cyc:.0f} cycles/yr (healthy is {low:.0f}-{high:.0f}). "
            "The battery rarely fills, likely overpaying for capacity."
        ),
        "no_savings": (
            "Estimated savings are ~0, little surplus to store; battery not worthwhile."
        ),
        "partial_year": (
            "Data covers only {days:.0f} days, cycles/year are annualized and may be skewed "
            "(summer cycles more than winter). Prefer a full year of data."
        ),
    },
}


def t(lang: str, key: str, **fmt) -> str:
    """UI string for `key` in `lang`, formatted with `fmt`. Falls back en -> raw key."""
    s = TR.get(lang, {}).get(key) or TR["en"].get(key) or key
    return s.format(**fmt) if fmt else s


def msg(lang: str, code: str, params: dict) -> str:
    """Render a recommend.py (code, params) message in `lang`."""
    s = MSG.get(lang, {}).get(code) or MSG["en"].get(code) or code
    return s.format(**params)
