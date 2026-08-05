#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vault-Recall-Tests (Stufe B) — Nutzer-Spezifikation (10 Fälle).

Testet core/retrieval.py mit isoliertem Index (temporärer Pfad), lokalen Embeddings
(bge-m3 via Ollama). Aufruf: python3 tests/test_vault_recall.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.retrieval as r

# Isolierten Index verwenden (niemals den echten Vault-Index berühren).
_TMP = tempfile.mkdtemp(prefix="retr-test-")
r.INDEX_PATH = os.path.join(_TMP, "vault_index.json")

OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    print(f"  {'✅' if cond else '❌'} {name} {detail}")
    if cond:
        OK += 1
    else:
        FAIL += 1


# --- Fixtures ----------------------------------------------------------------

def setup_vault():
    """Baut einen kleinen Vault: 1 relevant, 2 irrelevant + ein zweites relevantes."""
    r.remove_document("/wiki/Brandschutz.md")
    r.remove_document("/wiki/ErsteHilfe.md")
    r.remove_document("/wiki/Kaffee.md")
    r.remove_document("/wiki/Gefahrstoffe.md")
    r.index_document("Brandschutzordnung", "/wiki/Brandschutz.md",
                     "Die Brandschutzordnung regelt Löschmittel, Fluchtwege und den Sammelplatz. Feuerlöscher an Ausgängen.")
    r.index_document("Erste Hilfe", "/wiki/ErsteHilfe.md",
                     "Erste Hilfe umfasst Wundversorgung, Reanimation und Notruf 112. Verbandskasten vorgeschrieben.")
    r.index_document("Kaffeeanbau", "/wiki/Kaffee.md",
                     "Kaffee aus tropischen Hochlagen wird geröstet und gemahlen.")
    r.index_document("Gefahrstoffe", "/wiki/Gefahrstoffe.md",
                     "Gefahrstoffe werden gemäß CLP gelagert und mit Sicherheitsdatenblatt dokumentiert.")


# --- Tests -------------------------------------------------------------------

def test_1_relevante_treffer():
    print("\n[1] Relevantes Dokument wird gefunden:")
    setup_vault()
    res = r.search("Wo ist der Sammelplatz bei einem Brand?", top_k=4, min_score=0.5)
    check("Status success", res["status"] == "success", f"-> {res['status']}")
    paths = [x["path"] for x in res["results"]]
    check("Brandschutz.md in Treffern", "/wiki/Brandschutz.md" in paths, f"-> {paths}")
    check("Brandschutz-Score höchster", res["results"] and res["results"][0]["path"] == "/wiki/Brandschutz.md",
          f"-> {(res['results'][0]['score'] if res['results'] else 0):.3f}")


def test_2_irrelevante_unter_schwellwert():
    print("\n[2] Irrelevante Dokumente unter Schwellwert verworfen:")
    setup_vault()
    # Sehr spezifische Brand-Frage, hoher Schwellwert → Kaffee/ErsteHilfe fliegen raus.
    res = r.search("Sammelplatz Brandschutz Fluchtweg", top_k=4, min_score=0.6)
    paths = [x["path"] for x in res["results"]]
    check("Kaffee.md NICHT im Ergebnis", "/wiki/Kaffee.md" not in paths, f"-> {paths}")


def test_3_quellen_erhalten():
    print("\n[3] Quellen bleiben bis zur finalen Antwort erhalten:")
    setup_vault()
    res = r.search("Brandschutzordnung Sammelplatz", top_k=4, min_score=0.5)
    # results enthalten volle Metadaten (path, title, section) — ausreichend für Quellenangabe.
    ok = all("path" in x and "title" in x for x in res["results"])
    check("results tragen path+title", ok, f"-> {res['sources']}")
    check("sources-Feld gefüllt", bool(res["sources"]))


def test_4_leerer_vault():
    print("\n[4] Leerer Vault → keine erfundenen Inhalte:")
    r.save_index({"version": 1, "docs": []})  # Index leeren
    res = r.search("Irgendwas", top_k=4, min_score=0.3)
    check("Status empty oder 0 selected", res["status"] == "empty" or res["selected"] == 0,
          f"-> {res['status']} selected={res['selected']}")
    check("Keine results/erfundene Inhalte", not res.get("results"), "leer")
    setup_vault()  # Vault wiederherstellen


def test_5_aktualisierung():
    print("\n[5] Aktualisiertes Dokument ersetzt alte Embeddings:")
    setup_vault()
    # Gleicher Pfad, neuer Inhalt (Änderung) → Hash ändert sich → Reindex.
    res = r.index_document("Brandschutzordnung", "/wiki/Brandschutz.md", "NEUER INHALT: Brandschutz mit anderem Sammelplatz.")
    check("Neuer Inhalt → Reindex", res["status"] == "indexed", f"-> {res['status']}")
    # Alter Inhalt sollte nicht mehr in den Einträgen des Pfads stecken.
    docs = r.load_index()["docs"]
    brandschutz_docs = [d for d in docs if d["path"] == "/wiki/Brandschutz.md"]
    check("Alte Einträge ersetzt (nur neue Abschnitte)", all("anderem Sammelplatz" in d["text"] for d in brandschutz_docs),
          f"-> {len(brandschutz_docs)} Abschnitte")


def test_6_geloeschte_dokumente():
    print("\n[6] Gelöschtes Dokument wird nicht mehr gefunden:")
    setup_vault()
    r.remove_document("/wiki/Kaffee.md")
    res = r.search("Kaffee Röstung", top_k=4, min_score=0.0)  # niedriger Schwellwert, muss trotzdem raus
    check("Kaffee.md nicht mehr im Index", "/wiki/Kaffee.md" not in res["sources"], f"-> {res['sources']}")
    check("Nicht mehr in results", all(x["path"] != "/wiki/Kaffee.md" for x in res["results"]))


def test_7_mehrere_treffer_zusammengefuehrt():
    print("\n[7] Mehrere Treffer korrekt zusammengeführt:")
    setup_vault()
    r.index_document("Brandschutz Details", "/wiki/BrandschutzDetails.md", "Weitere Regeln: Feuerlöscher und Rauchabzug beim Brand.")
    res = r.search("Brand Feuerlöscher Sammelplatz", top_k=4, min_score=0.5)
    paths = [x["path"] for x in res["results"]]
    check("Beide Brandschutz-Dokumente", "/wiki/Brandschutz.md" in paths and "/wiki/BrandschutzDetails.md" in paths, f"-> {paths}")


def test_8_widersprueche_nicht_vereinheitlicht():
    print("\n[8] Widersprüchliche Quellen werden nicht stillschweigend vereinheitlicht:")
    setup_vault()
    r.index_document("Sammelplatz A", "/wiki/SammelplatzA.md", "Sammelplatz ist der Parkplatz Nord.")
    r.index_document("Sammelplatz B", "/wiki/SammelplatzB.md", "Sammelplatz ist der Innenhof Süd.")
    res = r.search("Wo ist der Sammelplatz?", top_k=4, min_score=0.5)
    paths = [x["path"] for x in res["results"] if "Sammelplatz" in x["path"]]
    check("Beide Sammelplatz-Quellen präsent (kein stillschweigender Merge)",
          "/wiki/SammelplatzA.md" in paths and "/wiki/SammelplatzB.md" in paths, f"-> {paths}")


def test_9_websearch_getrennt():
    print("\n[9] VaultRecall und WebSearch im Trace getrennt ausgewiesen:")
    setup_vault()
    from core import tool_loop as tl
    # Nur VaultRecall im Trace → retrieval gesetzt, WebSearch fehlt in tool_calls.
    vault_res = {"ok": True, "result": {"status": "success", "query": "q", "candidates": 3, "selected": 1,
                                        "threshold": 0.6, "sources": ["/wiki/B.md"], "top_k": 4, "error": None}}
    trace = tl._build_trace([{"tool": "VaultRecall", "ok": True}], [{"tool": "VaultRecall", "result": vault_res}])
    check("retrieval-Block vorhanden (vault)", trace.get("retrieval") is not None
          and trace["retrieval"].get("type") == "vault", f"-> {trace.get('retrieval') and trace['retrieval'].get('type')}")
    check("retrieval.status", trace["retrieval"]["status"] == "success")


def test_10_keine_web_behauptung():
    print("\n[10] Agent behauptet keine Webinformationen bei reiner Vault-Suche:")
    # Wenn nur VaultRecall lief, darf der retrieval-Block KEIN 'web'-Kennzeichen tragen
    # und der System-Prompt verlangt, dass VaultRecall als Vault (nicht Web) gilt.
    from core import tool_registry as tr
    tool = tr.TOOL_MAP.get("VaultRecall")
    # VaultRecall darf kein separater WebSearch sein und soll Vault (nicht Web-Recherche) sein.
    check("VaultRecall ist separates Tool (nicht WebSearch)", bool(tool) and tool["name"] != "WebSearch")
    # Beschreibung kennzeichnet es explizit als Vault-suche, nicht als Web-Recherche-Tool.
    check("VaultRecall-Beschreibung nennt Vault", tool and "Vault" in tool["description"],
          f"-> {tool['description'][:60] if tool else '?'}")


def test_11_keyword_boost_moc_unterschied():
    print("\n[11] Hybrid-Reranking: Grundlagen-MOC bei Unterschied-Frage in Top-5:")
    # Regressionsfall vom 2026-08-03: Frage enthält beide Begriffe; die Grundlagen-MOC
    # ('arbeitssicherheit' im Titel) muss trotz niedrigerem Vektor-Score nach vorne.
    r.remove_document("/wiki/AS/00 MOC - Arbeitssicherheit.md")
    r.remove_document("/wiki/AS/Maschinen.md")
    r.remove_document("/wiki/AS/Betriebsanweisungen.md")
    r.index_document("00 MOC - Arbeitssicherheit", "/wiki/AS/00 MOC - Arbeitssicherheit.md",
                     "Arbeitssicherheit und Arbeitsschutz sind eng verwandte Begriffe. "
                     "Arbeitssicherheit bezeichnet den Schutz vor Arbeitsunfällen und "
                     "Berufskrankheiten, Arbeitsschutz umfasst zusätzlich den Gesundheits- "
                     "und Gefahrenschutz am Arbeitsplatz.")
    r.index_document("Maschinen", "/wiki/AS/Maschinen.md",
                     "Maschinen müssen Sicherheitseinrichtungen, Schutzeinrichtungen und "
                     "Not-Aus haben. Anforderungen an Maschinen und Geräte regelt die "
                     "Maschinenrichtlinie und Betriebsanweisungen.")
    r.index_document("Betriebsanweisungen", "/wiki/AS/Betriebsanweisungen.md",
                     "Betriebsanweisungen beschreiben sicheres Verhalten, Umgang mit "
                     "Maschinen und Gefahrstoffen.")
    res = r.search("Was ist der Unterschied zwischen Arbeitsschutz und Arbeitssicherheit?",
                   top_k=5, min_score=0.5)
    paths = [x["path"] for x in res["results"]]
    check("MOC in Top-5", "/wiki/AS/00 MOC - Arbeitssicherheit.md" in paths,
          f"-> {paths}")
    check("MOC hat Boost > 0", any(x["boost"] > 0 for x in res["results"]
                                   if "00 MOC - Arbeitssicherheit" in x["path"]),
          f"-> boosts={[x['boost'] for x in res['results']]}")


if __name__ == "__main__":
    print("=== Vault-Recall-Tests (Stufe B) ===")
    test_1_relevante_treffer()
    test_2_irrelevante_unter_schwellwert()
    test_3_quellen_erhalten()
    test_4_leerer_vault()
    test_5_aktualisierung()
    test_6_geloeschte_dokumente()
    test_7_mehrere_treffer_zusammengefuehrt()
    test_8_widersprueche_nicht_vereinheitlicht()
    test_9_websearch_getrennt()
    test_10_keine_web_behauptung()
    test_11_keyword_boost_moc_unterschied()
    # Aufräumen
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)
