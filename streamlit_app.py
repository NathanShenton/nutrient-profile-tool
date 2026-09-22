"""Nutrient Profile Tool — Streamlit edition.

Run with: streamlit run app.py
Calculations are a transparent working aid and do not replace expert or regulatory sign-off.
"""
from __future__ import annotations

import json
import hashlib
import re
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Nutrient Profile Tool", page_icon="🌿", layout="wide")
CATEGORY_FILE = Path(__file__).with_name("dwh_odl_dim_categories_fpna.csv")
CATEGORY_COLUMNS = [
    "category_fpna_l1_name", "category_fpna_l2_name",
    "category_fpna_l3_name", "category_fpna_l4_name",
]
try:
    CATEGORY_TREE = pd.read_csv(CATEGORY_FILE, dtype=str).fillna("")
    CATEGORY_TREE = CATEGORY_TREE[CATEGORY_COLUMNS].drop_duplicates()
except (OSError, ValueError, KeyError):
    CATEGORY_TREE = pd.DataFrame(columns=CATEGORY_COLUMNS)


def _clear_category_children(level: int) -> None:
    """Clear lower-level selections when a parent picklist changes."""
    for child in range(level + 1, 5):
        st.session_state.pop(f"category_l{child}", None)


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');
:root { --forest:#174b3b; --deep:#103c30; --leaf:#80a944; --gold:#d5b66a; --cream:#f7f5ee; --ink:#263b32; }
.stApp { background:linear-gradient(180deg,#f7f5ee 0%,#fbfaf7 38%,#f6f5ef 100%); color:var(--ink); font-family:'DM Sans',sans-serif; }
[data-testid="stHeader"] { background:transparent; }
.block-container { max-width:1320px; padding-top:2.2rem; padding-bottom:4rem; }
h1,h2,h3 { color:#174b3b; }
h1 { font-family:'Playfair Display',serif; font-weight:700; letter-spacing:-.03em; }
h2,h3 { font-family:'Playfair Display',serif; }
[data-testid="stTabs"] button { border-radius:999px; padding:.55rem 1rem; }
[data-testid="stTabs"] button[aria-selected="true"] { background:#174b3b; color:white; }
[data-testid="stMetric"] { background:#fff; border:1px solid #e8e7dd; border-radius:18px; padding:1rem 1.15rem; box-shadow:0 5px 18px #174b3b0b; }
[data-testid="stForm"] { background:white; padding:1.2rem 1.4rem; border:1px solid #e8e7dd; border-radius:20px; }
div.stButton>button,div.stDownloadButton>button { border-radius:999px; border:0; background:#174b3b; color:white; font-weight:700; padding:.55rem 1.1rem; }
div.stButton>button:hover,div.stDownloadButton>button:hover { background:#28644d; color:white; }
.hero { background:radial-gradient(ellipse at 90% 0%,#3a735a 0,#174b3b 43%,#103c30 100%); color:#fff; padding:2.5rem 2.7rem; border-radius:26px; margin-bottom:1.4rem; box-shadow:0 18px 45px #174b3b22; }
.hero .eyebrow { color:#dce9bd; font-size:.75rem; text-transform:uppercase; letter-spacing:.15em; font-weight:700; }
.hero h1 { color:white; font-size:2.55rem; margin:.5rem 0 .4rem; }
.hero p { color:#e7eee7; max-width:800px; margin:0; font-size:1.04rem; }
.soft-card { padding:1.1rem 1.25rem; border-radius:18px; background:#fff; border:1px solid #e9e7dd; margin:.5rem 0 1rem; }
.leaf-note { padding:.9rem 1rem; background:#edf3e8; border-left:4px solid #80a944; border-radius:5px 14px 14px 5px; color:#345344; }
.amber-note { padding:.9rem 1rem; background:#fbf3df; border-left:4px solid #c69b3e; border-radius:5px 14px 14px 5px; color:#5b4a25; }
.muted { color:#718078; font-size:.88rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero"><div class="eyebrow">Nutrition Assessment</div>
<h1>Nutrient Profile Tool</h1>
<p>Calculate NPM scores, review the inputs and record product evidence.</p></div>
""", unsafe_allow_html=True)

NPM = {
    "2004/05": dict(id="NPM 2004/05", label="NPM 2004/05 · regulatory calculation",
        a=[("Energy (kJ)","energy",[335,670,1005,1340,1675,2010,2345,2680,3015,3350]),("Saturated fat (g)","sat",[1,2,3,4,5,6,7,8,9,10]),("Total sugars (g)","sugar",[4.5,9,13.5,18,22.5,27,31,36,40,45]),("Sodium (mg)","sodium",[90,180,270,360,450,540,630,720,810,900])], fibre={"NSP / Englyst":[.7,1.4,2.1,2.8,3.5],"AOAC":[.9,1.9,2.8,3.7,4.7]}, protein=[1.6,3.2,4.8,6.4,8], fv="fvn"),
    "2018": dict(id="NPM 2018", label="NPM 2018 · scenario / future-readiness", a=[("Energy (kJ)","energy",[315,630,945,1260,1575,1890,2205,2520,2835,3150]),("Saturated fat (g)","sat",[.9,1.9,2.8,3.7,4.7,5.6,6.6,7.5,8.4,9.4]),("Free sugars (g)","freeSugar",[.9,1.9,2.8,3.7,4.6,5.6,6.5,7.4,8.3,9.3]),("Salt (g)","salt",[.2,.5,.7,.9,1.1,1.4,1.6,1.8,2,2.3])], fibre={"AOAC":[.6,1.2,1.8,2.4,3,3.6,4.2,4.8,5.4,6]}, protein=[1.7,3.4,5.1,6.8,8.5], fv="fvns")
}

# Internal threshold reference transcribed from the supplied prototype.
# These are comparisons against entered values, not a governed compliance decision.
INTERNAL_THRESHOLDS = {
    "Banana and plantain chips": [("sugar", "<=", 15), ("sat", "<=", 19)],
    "Bread substitutes": [("sat", "<=", 2.8), ("fibre", ">=", 3), ("salt", "<=", 1.2)],
    "Breakfast cereals": [("sugar", "<=", 16), ("sat", "<=", 2.8), ("fibre", ">=", 6), ("salt", "<=", .9)],
    "Broths": [("salt", "<=", .59)],
    "Brown bread": [("fibre", ">", 10), ("salt", "<=", 1.08)],
    "Cakes": [("sugar", "<=", 15), ("sat", "<=", 11), ("salt", "<=", .66)],
    "Chewing gum and mints": [("addedSugarStatus", "no", None)],
    "Chips / crisps": [("sat", "<=", 3), ("salt", "<=", 1.1)],
    "Chocolate spread": [("sugar", "<=", 15), ("sat", "<=", 9)],
    "Cold tomato / vegetable sauces": [("sugar", "<=", 16), ("salt", "<=", 1.63)],
    "Cookies": [("sugar", "<=", 18), ("sat", "<=", 11), ("salt", "<=", .76)],
    "Dairy and plant-based drinks": [("sugar", "<=", 4.5)],
    "Emulsion-based sauces": [("salt", "<=", 1)],
    "Fruit and vegetable juices": [("addedSugarStatus", "no", None)],
    "Grain, muesli, fruit and energy bars": [("sugar", "<=", 20), ("sat", "<=", 5), ("salt", "<=", .4)],
    "Hot beverages": [("sugar", "<=", 4.5)],
    "Meat substitutes": [("sat", "<=", 18.1), ("salt", "<=", 1.3)],
    "Nut-based spreads": [("sugar", "<=", 10), ("sat", "<=", 6), ("salt", "<=", .84)],
    "Other savoury snacks": [("sat", "<=", 2.5), ("salt", "<=", 1.5)],
    "Other savoury spreads": [("sat", "<=", 2.5), ("salt", "<=", 1.1)],
    "Protein bar": [("sugar", "<=", 20), ("sat", "<=", 5), ("fibre", ">=", 6), ("salt", "<=", .8)],
    "Salted nuts and seeds": [("salt", "<=", 1.2)],
    "Soft drinks, energy drinks and prepared syrups": [("sugar", "<=", 4.5)],
    "Soups": [("salt", "<=", .59)],
    "Sweet spreads": [("sugar", "<=", 27)],
    "Sweets": [("sugar", "<=", 15)],
    "Warm tomato / vegetable sauces": [("salt", "<=", 1.1)],
    "Chocolate": [("sugar", "<=", 30)],
}
INTERNAL_METRIC_LABELS = {"sugar":"Total sugars", "sat":"Saturated fat", "salt":"Salt", "fibre":"Fibre", "protein":"Protein", "plantPoints":"Plant points", "proteinEnergyPct":"Energy from protein"}
INGREDIENT_REVIEW_PROMPTS = [
    ("Benzoates", ["benzoate", "benzoic acid"]),
    ("Nitrites and nitrates", ["nitrite", "nitrate"]),
    ("Phosphates and chelating agents", ["phosphate", "phosphoric acid", "EDTA", "ethylenediaminetetraacetic"]),
    ("Synthetic antioxidant review", ["BHA", "BHT", "TBHQ", "propyl gallate"]),
    ("Emulsifier review", ["emulsifier", "mono-and diglycerides", "mono and diglycerides", "monoand diglycerides", "mono-and diglyceride", "mono and diglyceride", "monoand diglyceride", "polysorbate"]),
    ("Artificial sweetener review", ["aspartame", "acesulfame", "saccharin", "cyclamate", "sucralose"]),
    ("Artificial colour review", ["artificial colour", "artificial color", "tartrazine", "sunset yellow", "quinoline yellow", "allura red"]),
    ("Processing-aid review", ["processing aid"]),
]
BULK_TEMPLATE_COLUMNS = [
    "sku_id", "sku_name", "product_type", "assessment_basis",
    "l1_category", "l2_category", "l3_category", "l4_category",
    "ingredients", "energy_kj", "saturated_fat_g", "total_sugars_g",
    "salt_g", "protein_g", "fibre_g", "fibre_method", "free_sugars_g",
    "fvn_percent", "fvns_percent", "nutrition_source", "specialist_source",
    "reviewer", "review_decision", "review_notes", "added_sugar_status",
    "internal_threshold_category", "plant_points", "protein_energy_percent",
]


def scan_ingredient_review(ingredients: str) -> list[dict]:
    """Return each keyword match with its source text, search term and review area."""
    source=ingredients or ""
    matches=[]
    for area,terms in INGREDIENT_REVIEW_PROMPTS:
        group_hits=[]
        occupied_spans=[]
        for term in sorted(terms,key=len,reverse=True):
            pattern=rf"\b{re.escape(term)}\b" if term.casefold() in {"bha","bht"} else re.escape(term)
            for found in re.finditer(pattern,source,flags=re.IGNORECASE):
                span=found.span()
                if any(span[0]<end and span[1]>start for start,end in occupied_spans):
                    continue
                occupied_spans.append(span)
                separators=[source.rfind(",",0,span[0]),source.rfind(";",0,span[0])]
                left=max(separators)+1
                following=[position for position in (source.find(",",span[1]),source.find(";",span[1])) if position>=0]
                right=min(following) if following else len(source)
                group_hits.append({"reviewArea":area,"matchedIngredient":source[left:right].strip(),"matchedText":found.group(0),"searchTerm":term,"_start":span[0]})
        matches.extend(sorted(group_hits,key=lambda item:item["_start"]))
    for item in matches:
        item.pop("_start",None)
    return matches


def safe_filename_part(value: str, fallback: str) -> str:
    cleaned=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value or "")).strip(" ._")
    cleaned=re.sub(r"\s+"," ",cleaned)
    return cleaned[:90] or fallback


def bulk_row_to_record(row: dict, index: int, run_timestamp: str, default_reviewer: str="") -> tuple[dict, str]:
    """Normalize one CSV row and produce its deterministic result record."""
    def cell(key):
        value=row.get(key,"")
        return "" if value is None else str(value).strip()
    sku=cell("sku_id"); name=cell("sku_name")
    kind_value=cell("product_type").casefold()
    kind="Drink" if kind_value in {"drink","beverage"} else "Food"
    basis_value=cell("assessment_basis").casefold()
    basis="Reconstituted to pack instructions" if any(word in basis_value for word in ("reconstituted","reconstituted to pack","prepared")) else "As sold"
    fibre_raw=cell("fibre_method").casefold()
    fibre_method="NSP / Englyst" if fibre_raw in {"nsp","englyst","nsp / englyst"} else "AOAC"
    added_raw=cell("added_sugar_status").casefold()
    if added_raw in {"no","no added sugar","confirmed no added sugar"}: added="Confirmed no added sugar"
    elif added_raw in {"yes","added","added sugar present"}: added="Added sugar present"
    else: added="Unknown — review needed"
    warnings=[]
    number_fields={"energy_kj":"energy","saturated_fat_g":"sat","total_sugars_g":"sugar","salt_g":"salt","protein_g":"protein","fibre_g":"fibre","free_sugars_g":"freeSugar","fvn_percent":"fvn","fvns_percent":"fvns","plant_points":"plantPoints","protein_energy_percent":"proteinEnergyPct"}
    values={}
    for source,target in number_fields.items():
        text=cell(source)
        if not text:
            values[target]=None
            continue
        try: value=float(text)
        except ValueError:
            values[target]=None; warnings.append(f"{source}: not numeric ({text})"); continue
        if value<0 or (target in {"fvn","fvns","proteinEnergyPct"} and value>100):
            values[target]=None; warnings.append(f"{source}: outside the accepted range ({text})"); continue
        values[target]=int(value) if target=="plantPoints" else value
    x={**values,"salt":values["salt"],"sodium":values["salt"]*400 if values["salt"] is not None else None,"fibreMethod":fibre_method}
    threshold_category=cell("internal_threshold_category")
    if threshold_category not in INTERNAL_THRESHOLDS:
        threshold_category=""
    reviewer=cell("reviewer") or default_reviewer
    inputs={"sku":sku,"name":name,"product_type":kind,"assessment_basis":basis,
        "l1":cell("l1_category"),"l2":cell("l2_category"),"l3":cell("l3_category"),"l4":cell("l4_category"),
        "ingredients":cell("ingredients"),"reviewer":reviewer,
        "review_decision":cell("review_decision") or "Not reviewed","review_notes":cell("review_notes"),
        "nutrition_source":cell("nutrition_source"),"specialist_source":cell("specialist_source"),
        "addedSugarStatus":added,**x}
    results=[score_model(model,x,kind) for model in NPM]
    record={"timestamp":run_timestamp,"rulesetBuild":"2026-09-10 v0.1","runType":"bulk user calculation",
        "inputs":inputs,"results":results,"inputWarnings":warnings,
        "ingredientPromptMatches":scan_ingredient_review(inputs["ingredients"]),
        "internalThresholdCheck":{"category":threshold_category,"rows":check_internal_thresholds(threshold_category,x,added) if threshold_category else []}}
    filename=f"{safe_filename_part(sku,'SKU')} - {safe_filename_part(name,'Product')}.pdf"
    return record,filename


def check_internal_thresholds(category: str, x: dict, added_sugar: str) -> list[dict]:
    values={"sugar":x.get("sugar"),"sat":x.get("sat"),"salt":x.get("salt"),"fibre":x.get("fibre"),"protein":x.get("protein"),"plantPoints":x.get("plantPoints"),"proteinEnergyPct":x.get("proteinEnergyPct")}
    rows=[]
    for key,operator,target in INTERNAL_THRESHOLDS[category]:
        label="Added-sugar status" if key=="addedSugarStatus" else INTERNAL_METRIC_LABELS[key]
        if key=="addedSugarStatus":
            status="PENDING" if added_sugar=="Unknown — review needed" else ("PASS" if added_sugar=="Confirmed no added sugar" else "FAIL")
            observed=added_sugar
            target_text="No added sugar"
        else:
            observed=values[key]
            unit="points" if key=="plantPoints" else "%" if key=="proteinEnergyPct" else "g"
            target_text=f"{operator} {fmt(target)} {unit}"
            if observed is None:
                status="PENDING"
            else:
                passed={"<=":observed<=target,">=":observed>=target,"<":observed<target,">":observed>target}[operator]
                status="PASS" if passed else "FAIL"
            observed="Not entered" if observed is None else f"{fmt(observed)} {unit}"
        rows.append({"Nutrient / criterion":label,"Entered value":observed,"Threshold":target_text,"Status":status})
    return rows

def points(value, thresholds): return sum(value > t for t in thresholds)
def fmt(v): return f"{v:g}"
def score_model(model, x, kind):
    r=NPM[model]; required={"2004/05":["energy","sat","sugar","salt","protein","fibre","fvn"],"2018":["energy","sat","salt","protein","fibre","fvns","freeSugar"]}[model]
    missing=[k for k in required if x.get(k) is None]
    if model=="2018" and x.get("fibreMethod")!="AOAC": missing.append("AOAC fibre method")
    if missing: return {"model":model,"blocked":True,"missing":list(dict.fromkeys(missing))}
    arows=[]; A=0
    for label,key,limits in r["a"]:
        v=x["sodium"] if key=="sodium" else x[key]; p=points(v,limits); A+=p
        arows.append({"Group":"A","Input":label,"Value":fmt(v),"Threshold applied":("≤ "+fmt(limits[0]) if p==0 else "> "+fmt(limits[p-1])),"Points":p,"Included":"Yes"})
    fv=x[r["fv"]]; fvp=5 if fv>80 else 2 if fv>60 else 1 if fv>40 else 0
    flimits=r["fibre"][x["fibreMethod"] if model=="2004/05" else "AOAC"]
    fp=points(x["fibre"],flimits); pp=points(x["protein"],r["protein"]); protein_used=not(A>=11 and fvp<5)
    for label,v,lim,p in [("FVN / FVNS (%)",fv,[40,60,80],fvp),("Fibre (g)",x["fibre"],flimits,fp),("Protein (g)",x["protein"],r["protein"],pp)]:
        arows.append({"Group":"C","Input":label,"Value":fmt(v),"Threshold applied":("≤ "+fmt(lim[0]) if p==0 else "> "+fmt(lim[p-1])),"Points":p,"Included":"Yes" if label!="Protein (g)" or protein_used else "No · protein gate"})
    C=fvp+fp+(pp if protein_used else 0); total=A-C; threshold=1 if kind=="Drink" else 4
    return {"model":model,"blocked":False,"A":A,"C":C,"score":total,"threshold":threshold,"classification":"Less healthy" if total>=threshold else "Not less healthy","protein_used":protein_used,"ledger":arows,"notes":"Salt converted to sodium (salt × 400)." if model=="2004/05" else "Comparison scenario uses verified free sugars and FVNS values."}


def point_band_tables(model: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return scoring bands as implemented, for reviewer inspection."""
    rule=NPM[model]
    def cutoff_band(point: int, thresholds: list[float], unit: str) -> str:
        if point==0: return f"≤ {fmt(thresholds[0])} {unit}"
        if point<=len(thresholds): return f"> {fmt(thresholds[point-1])} {unit}"
        return "Not applicable"
    a_rows=[]
    for point in range(11):
        row={"Points":point}
        for label,key,thresholds in rule["a"]:
            unit="kJ" if key=="energy" else "mg sodium" if key=="sodium" else "g"
            row[label]=cutoff_band(point,thresholds,unit)
        a_rows.append(row)
    fv_bands={0:"≤ 40%",1:"> 40% to ≤ 60%",2:"> 60% to ≤ 80%",3:"Not applicable",4:"Not applicable",5:"> 80%"}
    c_rows=[]
    for point in range(11):
        if model=="2004/05":
            row={"Points":point,"FVN (%)":fv_bands.get(point,"Not applicable"),
                 "Fibre · NSP (g)":cutoff_band(point,rule["fibre"]["NSP / Englyst"],"g"),
                 "Fibre · AOAC (g)":cutoff_band(point,rule["fibre"]["AOAC"],"g"),
                 "Protein (g)":cutoff_band(point,rule["protein"],"g")}
        else:
            row={"Points":point,"FVNS (%)":fv_bands.get(point,"Not applicable"),
                 "Fibre · AOAC (g)":cutoff_band(point,rule["fibre"]["AOAC"],"g"),
                 "Protein (g)":cutoff_band(point,rule["protein"],"g")}
        c_rows.append(row)
    return pd.DataFrame(a_rows),pd.DataFrame(c_rows)


def build_assessment_pdf(record: dict) -> bytes:
    """Create a compact, printable evidence report for the current assessment."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle, KeepTogether)

    ink=colors.HexColor("#263B32"); forest=colors.HexColor("#174B3B")
    pale=colors.HexColor("#EEF3E9"); line=colors.HexColor("#D9E2D8")
    muted=colors.HexColor("#66756D"); amber=colors.HexColor("#FBF3DF")
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=17*mm,leftMargin=17*mm,
                          topMargin=19*mm,bottomMargin=17*mm,
                          title="Nutrition Product Assessment",author="Nutrition Product Tool")
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=20,leading=24,textColor=forest,alignment=TA_LEFT,spaceAfter=3))
    styles.add(ParagraphStyle(name="Section",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=11,leading=14,textColor=forest,spaceBefore=10,spaceAfter=5,keepWithNext=True))
    styles.add(ParagraphStyle(name="BodySmall",parent=styles["BodyText"],fontName="Helvetica",fontSize=8.2,leading=11,textColor=ink))
    styles.add(ParagraphStyle(name="MutedSmall",parent=styles["BodyText"],fontName="Helvetica",fontSize=7.5,leading=10,textColor=muted))
    styles.add(ParagraphStyle(name="TableHead",parent=styles["BodyText"],fontName="Helvetica-Bold",fontSize=7.4,leading=9,textColor=colors.white))
    styles.add(ParagraphStyle(name="TableCell",parent=styles["BodyText"],fontName="Helvetica",fontSize=7.2,leading=9,textColor=ink))
    styles.add(ParagraphStyle(name="MetaLabel",parent=styles["BodyText"],fontName="Helvetica-Bold",fontSize=6.8,leading=8,textColor=forest))
    def para(value, style="TableCell"):
        # ReportLab's built-in Helvetica is reliable for standard ASCII. Replace
        # unsupported characters rather than letting a product name break export.
        clean=str(value if value not in (None,"") else "Not provided").encode("latin-1","replace").decode("latin-1")
        return Paragraph(escape(clean),styles[style])
    def grid(data,widths,header=True):
        t=Table(data,colWidths=widths,repeatRows=1 if header else 0,hAlign="LEFT")
        cmds=[("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("LINEBELOW",(0,0),(-1,-1),.35,line)]
        if header: cmds += [("BACKGROUND",(0,0),(-1,0),forest),("TEXTCOLOR",(0,0),(-1,0),colors.white)]
        t.setStyle(TableStyle(cmds)); return t
    inp=record.get("inputs",{}); results=record.get("results",[])
    run_at=record.get("timestamp","")
    try: run_at=datetime.fromisoformat(run_at).astimezone().strftime("%d %b %Y, %H:%M %Z")
    except (ValueError,TypeError): run_at=str(run_at or "Not available")
    story=[Paragraph("Nutrition Product Assessment",styles["ReportTitle"]),
           Paragraph("NPM calculation record · generated from entered product data",styles["MutedSmall"]),Spacer(1,8)]
    meta=[
        [para("DATE RUN","MetaLabel"),para(run_at),para("USER / REVIEWER","MetaLabel"),para(inp.get("reviewer"))],
        [para("PRODUCT ID","MetaLabel"),para(inp.get("sku")),para("PRODUCT NAME","MetaLabel"),para(inp.get("name"))],
        [para("PRODUCT TYPE","MetaLabel"),para(inp.get("product_type")),para("ASSESSMENT BASIS","MetaLabel"),para(inp.get("assessment_basis"))],
        [para("REVIEW DECISION","MetaLabel"),para(inp.get("review_decision")),para("RUN TYPE","MetaLabel"),para(record.get("runType"))],
        [para("RULESET","MetaLabel"),para(record.get("rulesetBuild")),para("FIBRE METHOD","MetaLabel"),para(inp.get("fibreMethod"))],
    ]
    meta_table=Table(meta,colWidths=[25*mm,58*mm,29*mm,58*mm],hAlign="LEFT")
    meta_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),pale),("BOX",(0,0),(-1,-1),.6,line),("INNERGRID",(0,0),(-1,-1),.35,line),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story.extend([meta_table,Paragraph("NPM results",styles["Section"])])
    summary=[[para(x,"TableHead") for x in ["MODEL","STATUS","SCORE","THRESHOLD","A POINTS","C POINTS"]]]
    for res in results:
        summary.append([para(NPM[res["model"]]["id"]),para("Blocked - missing evidence" if res["blocked"] else res["classification"]),para("-" if res["blocked"] else res["score"]),para("-" if res["blocked"] else res["threshold"]),para("-" if res["blocked"] else res["A"]),para("-" if res["blocked"] else res["C"])])
    story.append(grid(summary,[36*mm,49*mm,17*mm,23*mm,20*mm,20*mm]))
    story.append(Paragraph("Assessment inputs",styles["Section"]))
    input_rows=[[para("NUTRITION VALUE","TableHead"),para("ENTERED VALUE","TableHead"),para("SPECIALIST / EVIDENCE","TableHead")]]
    for label,key,unit in [("Energy","energy","kJ"),("Saturated fat","sat","g"),("Total sugars","sugar","g"),("Free sugars","freeSugar","g"),("Salt","salt","g"),("Protein","protein","g"),("Fibre","fibre","g"),("FVN","fvn","%"),("FVNS","fvns","%")]:
        v=inp.get(key)
        input_rows.append([para(label),para("Not entered" if v is None else f"{fmt(v)} {unit}"),para(inp.get("nutrition_source") if key in ("energy","sat","sugar","salt","protein","fibre") else inp.get("specialist_source"))])
    story.append(grid(input_rows,[48*mm,36*mm,81*mm]))
    cat=[("L1 category","l1"),("L2 category","l2"),("L3 category","l3"),("L4 category","l4")]
    story.append(Paragraph("Product classification & review",styles["Section"]))
    story.append(grid([[para("CATEGORY LEVEL","TableHead"),para("SELECTION","TableHead")]]+[[para(label),para(inp.get(key))] for label,key in cat], [48*mm,117*mm]))
    if inp.get("review_notes"):
        story.extend([Spacer(1,5),para("Review note: "+inp["review_notes"],"BodySmall")])
    if inp.get("ingredients"):
        story.extend([Paragraph("Ingredient declaration",styles["Section"]),para(inp["ingredients"],"BodySmall")])
    story.append(Paragraph("Ingredient review prompts",styles["Section"]))
    prompt_matches=record.get("ingredientPromptMatches",[])
    if not inp.get("ingredients"):
        story.append(para("No ingredient declaration was provided; keyword review was not run.","BodySmall"))
    elif prompt_matches:
        story.append(para("The following text matched the app's keyword list. Review each item against the controlled additive policy; this is not a compliance decision.","MutedSmall"))
        prompt_rows=[[para(x,"TableHead") for x in ["REVIEW AREA","INGREDIENT TEXT (AS ENTERED)","MATCHED TEXT","SEARCH TERM"]]]
        prompt_rows.extend([[para(item.get("reviewArea")),para(item.get("matchedIngredient")),para(item.get("matchedText")),para(item.get("searchTerm"))] for item in prompt_matches])
        story.append(grid(prompt_rows,[38*mm,61*mm,32*mm,34*mm]))
    else:
        story.append(para("No prototype keyword prompts found. This does not confirm policy compliance.","BodySmall"))
    story.append(para("Keyword matching only; check the ingredient and its function against the current controlled policy.","MutedSmall"))
    story.append(Paragraph("Internal threshold comparison",styles["Section"]))
    internal_check=record.get("internalThresholdCheck") or {}
    if not internal_check.get("category"):
        story.append(para("No internal threshold category was selected; comparison was not assessed.","BodySmall"))
    else:
        story.append(para(f"Selected reference category: {internal_check['category']}. Status compares entered values with the threshold transcription; it is not a governed compliance decision.","MutedSmall"))
        threshold_rows=internal_check.get("rows",[])
        if threshold_rows:
            table_rows=[[para(x,"TableHead") for x in ["NUTRIENT / CRITERION","ENTERED VALUE","THRESHOLD","STATUS"]]]
            for item in threshold_rows:
                table_rows.append([para(item.get("Nutrient / criterion")),para(item.get("Entered value")),para(item.get("Threshold")),para(item.get("Status"))])
            story.append(grid(table_rows,[48*mm,45*mm,40*mm,32*mm]))
        else:
            story.append(para("Threshold category could not be evaluated.","BodySmall"))
        story.append(para("Confirm category mapping, units and limits against the current controlled internal policy before using this comparison.","MutedSmall"))
    warnings=record.get("inputWarnings",[])
    if warnings:
        story.append(Paragraph("Bulk input warnings",styles["Section"]))
        for warning in warnings: story.append(para("- "+warning,"BodySmall"))
    story.append(Paragraph("Calculation detail",styles["Section"]))
    for res in results:
        block=[Paragraph(NPM[res["model"]]["label"],styles["BodySmall"])]
        if res["blocked"]:
            block.append(para("Calculation blocked. Missing or invalid: "+", ".join(res["missing"]),"BodySmall"))
        else:
            rows=[[para(x,"TableHead") for x in ["GROUP","INPUT","VALUE","THRESHOLD","POINTS","INCLUDED"]]]
            for row in res["ledger"]:
                rows.append([para(row[k]) for k in ["Group","Input","Value","Threshold applied","Points","Included"]])
            block.append(grid(rows,[14*mm,43*mm,22*mm,35*mm,17*mm,34*mm]))
            block.append(para(f"A {res['A']} - C {res['C']} = {res['score']}. {res['notes']}","MutedSmall"))
        story.extend([KeepTogether(block),Spacer(1,6)])
    story.extend([Spacer(1,8),para("This report records entered data and deterministic calculations. It is a working aid and does not replace regulatory review, evidence verification or product sign-off.","MutedSmall")])
    story.append(Paragraph("Method references",styles["Section"]))
    story.append(Paragraph('NPM 2004/05: <link href="https://assets.publishing.service.gov.uk/media/695e87982a4a53b73d513855/NutrientProfilingModel_2004_2005_TechnicalGuidance.pdf" color="#174B3B">Department of Health technical guidance (2011)</link><br/>NPM 2018: <link href="https://www.gov.uk/government/publications/nutrient-profiling-model-2018/nutrient-profiling-model-2018-technical-guidance" color="#174B3B">DHSC technical guidance</link>. The NPM 2018 publication page states this model is not yet applied to policy.',styles["MutedSmall"]))
    def footer(canvas,document):
        canvas.saveState(); w,h=A4
        canvas.setStrokeColor(line); canvas.line(17*mm,13*mm,w-17*mm,13*mm)
        canvas.setFont("Helvetica",7); canvas.setFillColor(muted)
        canvas.drawString(17*mm,8*mm,"Nutrition Product Tool | Assessment evidence")
        canvas.drawRightString(w-17*mm,8*mm,f"Page {document.page}")
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

with st.sidebar:
    st.markdown("### Your assessment")
    st.caption("One product at a time · values per 100 g or 100 ml")
    sku=st.text_input("SKU ID",placeholder="e.g. SKU-10482")
    name=st.text_input("Product name",placeholder="e.g. Berry oat bar")
    kind=st.selectbox("Product type",["Food","Drink"])
    basis=st.selectbox("Assessment basis",["As sold","Reconstituted to pack instructions"])
    st.markdown("---")
    st.caption("Reference values only. Reconstituted products should use values after preparation as directed.")

assessment, bulk, scope, policy, audit, guide = st.tabs(["✦  Product assessment","Bulk upload","✧  Category estimate","❋  Nutrition thresholds","Calculation logic & audit","Guide & controls"])
with assessment:
    st.markdown("## A clearer picture of your product")
    st.markdown('<div class="muted">Use verified supplier or laboratory data. Specialist values should come from an approved source.</div>',unsafe_allow_html=True)
    left,right=st.columns([1.08,.92],gap="large")
    with left:
        with st.container(border=True):
            st.markdown("### Product details & review")
            c1,c2=st.columns(2)
            with c1:
                if CATEGORY_TREE.empty:
                    st.error("Category dictionary not found or has unexpected columns. Keep the supplied CSV beside app.py.")
                    l1=l2=l3=l4=""
                else:
                    l1_options=sorted(CATEGORY_TREE[CATEGORY_COLUMNS[0]].loc[lambda s:s.ne("")].unique().tolist())
                    l1=st.selectbox("L1 category",[""]+l1_options,key="category_l1",format_func=lambda v:v or "Select L1 category",on_change=_clear_category_children,args=(1,))
                    l2_options=sorted(CATEGORY_TREE.loc[CATEGORY_TREE[CATEGORY_COLUMNS[0]].eq(l1),CATEGORY_COLUMNS[1]].loc[lambda s:s.ne("")].unique().tolist()) if l1 else []
                    l2=st.selectbox("L2 category",[""]+l2_options,key="category_l2",disabled=not bool(l1),format_func=lambda v:v or ("Select L2 category" if l1 else "Select L1 first"),on_change=_clear_category_children,args=(2,))
                    l3_options=sorted(CATEGORY_TREE.loc[CATEGORY_TREE[CATEGORY_COLUMNS[1]].eq(l2)&CATEGORY_TREE[CATEGORY_COLUMNS[0]].eq(l1),CATEGORY_COLUMNS[2]].loc[lambda s:s.ne("")].unique().tolist()) if l2 else []
                    l3=st.selectbox("L3 category",[""]+l3_options,key="category_l3",disabled=not bool(l2),format_func=lambda v:v or ("Select L3 category" if l2 else "Select L2 first"),on_change=_clear_category_children,args=(3,))
                    l4_options=sorted(CATEGORY_TREE.loc[CATEGORY_TREE[CATEGORY_COLUMNS[2]].eq(l3)&CATEGORY_TREE[CATEGORY_COLUMNS[1]].eq(l2)&CATEGORY_TREE[CATEGORY_COLUMNS[0]].eq(l1),CATEGORY_COLUMNS[3]].loc[lambda s:s.ne("")].unique().tolist()) if l3 else []
                    l4=st.selectbox("L4 category",[""]+l4_options,key="category_l4",disabled=not bool(l3),format_func=lambda v:v or ("Select L4 category" if l3 else "Select L3 first"))
            with c2: reviewer=st.text_input("User / reviewer"); decision=st.selectbox("Reviewer decision",["Not reviewed","Accepted","Accepted with caveat","Overridden"]); nutrition_source=st.text_input("Nutrition source"); specialist_source=st.text_input("Specialist data source")
            ingredients=st.text_area("Ingredient declaration",height=110,placeholder="Paste the legal ingredient declaration. Text is stored as evidence; it is not used to infer NPM inputs.")
            review_notes=st.text_area("Review rationale / caveat",height=70)
        with st.container(border=True):
            st.markdown("### Nutrition per 100")
            st.caption("Do not use rounded serving values. Salt is converted to sodium for NPM 2004/05.")
            c1,c2,c3=st.columns(3)
            with c1: energy=st.number_input("Energy · kJ",min_value=0.0,value=None,step=1.0,placeholder="Required"); sat=st.number_input("Saturated fat · g",min_value=0.0,value=None,step=.1,placeholder="Required"); sugar=st.number_input("Total sugars · g",min_value=0.0,value=None,step=.1,placeholder="2004/05")
            with c2: salt=st.number_input("Salt · g",min_value=0.0,value=None,step=.01,placeholder="Required"); protein=st.number_input("Protein · g",min_value=0.0,value=None,step=.1,placeholder="Required"); fibre=st.number_input("Fibre · g",min_value=0.0,value=None,step=.1,placeholder="Required")
            with c3: free_sugar=st.number_input("Free sugars · g",min_value=0.0,value=None,step=.1,placeholder="2018"); fibre_method=st.selectbox("Fibre method",["AOAC","NSP / Englyst"]); added=st.selectbox("Added-sugar status",["Unknown — review needed","Confirmed no added sugar","Added sugar present"])
        with st.container(border=True):
            st.markdown("### Specialist values & evidence")
            c1,c2=st.columns(2)
            with c1: fvn=st.number_input("FVN · % (2004/05)",min_value=0.0,max_value=100.0,value=None,step=.1,placeholder="Verified value"); fvns=st.number_input("FVNS · % (2018)",min_value=0.0,max_value=100.0,value=None,step=.1,placeholder="Verified value")
            with c2: plant=st.number_input("Plant points · internal policy input",min_value=0,value=None,step=1); protein_pct=st.number_input("Energy from protein · %",min_value=0.0,max_value=100.0,value=None,step=.1)
            st.markdown('<div class="amber-note">FVN, FVNS and free sugars must not be inferred from an ingredient list alone. Missing verified values block the relevant model.</div>',unsafe_allow_html=True)
            calc=st.button("Calculate both NPM models",type="primary",use_container_width=True)
            example=st.button("Load worked 2004/05 example")
    x={"energy":energy,"sat":sat,"sugar":sugar,"salt":salt,"sodium":salt*400 if salt is not None else None,"protein":protein,"fibre":fibre,"freeSugar":free_sugar,"fvn":fvn,"fvns":fvns,"fibreMethod":fibre_method,"plantPoints":plant,"proteinEnergyPct":protein_pct}
    current_inputs={"sku":sku,"name":name,"product_type":kind,"assessment_basis":basis,"l1":l1,"l2":l2,"l3":l3,"l4":l4,"ingredients":ingredients,"reviewer":reviewer,"review_decision":decision,"review_notes":review_notes,"nutrition_source":nutrition_source,"specialist_source":specialist_source,"addedSugarStatus":added,**x}
    if example:
        example_x={**x,"energy":459,"sat":1.8,"sugar":13.4,"salt":.00025,"sodium":.1,"protein":6.5,"fibre":.6,"fvn":8,"fvns":None,"freeSugar":None,"fibreMethod":"AOAC"}
        example_inputs={**current_inputs,"sku":"EX-2004-001","name":"Official example: fruit fromage frais","product_type":"Food","nutrition_source":"NPM 2004/05 technical guidance, worked example 1","specialist_source":"NPM 2004/05 technical guidance, worked example 1",**example_x}
        st.session_state["assessment_run"]={"timestamp":datetime.now(timezone.utc).isoformat(),"inputs":example_inputs,"results":[score_model(m,example_x,"Food") for m in NPM],"source":"official worked example"}
    if calc:
        st.session_state["assessment_run"]={"timestamp":datetime.now(timezone.utc).isoformat(),"inputs":current_inputs,"results":[score_model(m,x,kind) for m in NPM],"source":"user calculation"}
    with right:
        st.markdown("### Your NPM results")
        st.caption("Both models run together. NPM 2018 remains a comparison scenario until its business application is confirmed.")
        run=st.session_state.get("assessment_run")
        results=run["results"] if run else None
        input_changed=bool(run and run["source"]=="user calculation" and run["inputs"]!=current_inputs)
        if input_changed:
            st.warning("Inputs have changed since this result was calculated. Recalculate before exporting an evidence record.")
        if not results:
            st.markdown('<div class="leaf-note">Your results will appear here once you have entered the verified product data and selected <b>Calculate both NPM models</b>.</div>',unsafe_allow_html=True)
        else:
            for r in results:
                with st.container(border=True):
                    st.markdown(f"#### {NPM[r['model']]['label']}")
                    if r["blocked"]:
                        st.warning("Calculation needs verified values: " + ", ".join(r["missing"]))
                    else:
                        st.metric("NPM score",r["score"],delta=r["classification"],delta_color="inverse" if r["classification"]=="Less healthy" else "normal")
                        a,b,c=st.columns(3); a.metric("A points",r["A"]); b.metric("C points",r["C"]); c.metric("Food / drink threshold",r["threshold"])
                        st.caption(f"A {r['A']} − C {r['C']} = {r['score']}. Protein points {'included' if r['protein_used'] else 'excluded by the A ≥ 11 and FVN/FVNS < 5 gate'}. {r['notes']}")
            st.markdown("#### Calculation ledger")
            for r in results:
                st.markdown(f"**{NPM[r['model']]['id']}**")
                if not r["blocked"]: st.dataframe(pd.DataFrame(r["ledger"]),hide_index=True,use_container_width=True)
        st.markdown("### Internal threshold check")
        st.caption("Choose a product category to compare its entered nutrient values with the reference thresholds.")
        internal_category=st.selectbox("Internal threshold category",list(INTERNAL_THRESHOLDS),key="internal_threshold_category")
        run_internal_check=st.button("Check selected threshold",key="run_internal_check",use_container_width=True)
        threshold_inputs={**x,"addedSugarStatus":added}
        if run_internal_check:
            st.session_state["internal_check_result"]={"category":internal_category,"inputs":threshold_inputs,"rows":check_internal_thresholds(internal_category,x,added)}
        saved_internal=st.session_state.get("internal_check_result")
        if saved_internal:
            if saved_internal["category"]!=internal_category or saved_internal["inputs"]!=threshold_inputs:
                st.info("Product values or category have changed since the last check. Run the check again.")
            else:
                failed=[row["Nutrient / criterion"] for row in saved_internal["rows"] if row["Status"]=="FAIL"]
                pending=[row["Nutrient / criterion"] for row in saved_internal["rows"] if row["Status"]=="PENDING"]
                if failed: st.error("Outside selected threshold: " + ", ".join(failed))
                elif pending: st.warning("Check incomplete. Add or confirm: " + ", ".join(pending))
                else: st.success("All checked criteria are within the selected thresholds.")
                st.dataframe(pd.DataFrame(saved_internal["rows"]),hide_index=True,use_container_width=True)
                st.caption("Reference comparison only; confirm thresholds against the current controlled internal policy before making a product decision.")
        if results:
            run_inputs=run["inputs"]
            record={"timestamp":run["timestamp"],"rulesetBuild":"2026-09-10 v0.1","runType":run["source"],"inputs":run_inputs,"results":results,
                    "ingredientPromptMatches":scan_ingredient_review(run_inputs.get("ingredients","")),
                    "internalThresholdCheck":{"category":internal_category,"rows":check_internal_thresholds(internal_category,run_inputs,run_inputs.get("addedSugarStatus","Unknown — review needed"))},"inputWarnings":[]}
            prompt_matches=record["ingredientPromptMatches"]
            with st.expander(f"Ingredient review prompts · {len(prompt_matches)} match(es)",expanded=bool(prompt_matches)):
                if prompt_matches:
                    st.dataframe(pd.DataFrame(prompt_matches).rename(columns={"reviewArea":"Review area","matchedIngredient":"Ingredient text (as entered)","matchedText":"Matched text","searchTerm":"Search term"}),hide_index=True,use_container_width=True)
                    st.caption("Keyword matches need review against the controlled additive policy; they are not a compliance decision.")
                elif run_inputs.get("ingredients"):
                    st.caption("No prototype keyword prompts found in the ingredient declaration. This does not confirm compliance.")
                else:
                    st.caption("No ingredient declaration was provided; keyword review was not run.")
            safe_sku=re.sub(r'[^a-zA-Z0-9_-]','-',run["inputs"].get("sku") or 'draft')
            json_col,pdf_col=st.columns(2)
            with json_col:
                st.download_button("Download assessment record · JSON",json.dumps(record,indent=2),file_name=f"nutrition-assessment-{safe_sku}.json",mime="application/json",use_container_width=True,disabled=input_changed)
            with pdf_col:
                try:
                    pdf_bytes=build_assessment_pdf(record)
                except ModuleNotFoundError as exc:
                    if exc.name and exc.name.startswith("reportlab"):
                        st.warning("PDF export needs reportlab. Add reportlab = \"*\" to pyproject.toml and redeploy.")
                    else:
                        raise
                else:
                    st.download_button("Download assessment report · PDF",pdf_bytes,file_name=f"nutrition-assessment-{safe_sku}.pdf",mime="application/pdf",use_container_width=True,disabled=input_changed)

with bulk:
    st.markdown("## Bulk assessment")
    st.caption("Upload up to 10 products. The tool calculates both NPM models and creates one PDF per SKU.")
    template = pd.DataFrame(columns=BULK_TEMPLATE_COLUMNS).to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV template",template,file_name="npm_bulk_input_template.csv",mime="text/csv",key="bulk_template_download")
    st.markdown("Fill one row per SKU. Enter nutrient values per 100 g or 100 ml. Use `Food` or `Drink` for product_type. The internal threshold category must match a category listed in the Nutrition thresholds tab. Leave unknown numeric values blank; the report will show when a model cannot be calculated.")
    with st.expander("Valid internal threshold categories"):
        st.write(", ".join(INTERNAL_THRESHOLDS.keys()))
    bulk_reviewer=st.text_input("Default user / reviewer",key="bulk_default_reviewer")
    if st.session_state.get("bulk_pdf_outputs") and st.session_state.get("bulk_reviewer_for_outputs")!=bulk_reviewer:
        st.session_state.pop("bulk_pdf_outputs",None)
    bulk_file=st.file_uploader("Upload completed template",type=["csv"],key="bulk_csv_upload")
    bulk_source_hash=None
    bulk_df=None
    bulk_errors=[]
    if bulk_file is not None:
        bulk_bytes=bulk_file.getvalue()
        bulk_source_hash=hashlib.sha256(bulk_bytes).hexdigest()
        if st.session_state.get("bulk_source_hash") not in (None,bulk_source_hash):
            st.session_state.pop("bulk_pdf_outputs",None)
        try:
            bulk_df=pd.read_csv(BytesIO(bulk_bytes),dtype=str,keep_default_na=False)
            bulk_df.columns=[str(col).strip().lower() for col in bulk_df.columns]
            if bulk_df.columns.duplicated().any():
                bulk_errors.append("The CSV has duplicate column names after trimming spaces and converting to lowercase.")
            missing_headers=sorted(set(BULK_TEMPLATE_COLUMNS[:3]+["internal_threshold_category"])-set(bulk_df.columns))
            if missing_headers:
                bulk_errors.append("Missing required columns: "+", ".join(missing_headers))
            if len(bulk_df)>10:
                bulk_errors.append(f"The file has {len(bulk_df)} product rows. Upload no more than 10 at a time.")
            if len(bulk_df)==0:
                bulk_errors.append("The CSV has no product rows.")
            if not bulk_errors:
                for row_index,row in bulk_df.iterrows():
                    row_num=row_index+2
                    sku_value=str(row.get("sku_id","")).strip()
                    name_value=str(row.get("sku_name","")).strip()
                    kind_value=str(row.get("product_type","")).strip().casefold()
                    category_value=str(row.get("internal_threshold_category","")).strip()
                    if not sku_value: bulk_errors.append(f"Row {row_num}: SKU ID is required.")
                    if not name_value: bulk_errors.append(f"Row {row_num}: SKU name is required.")
                    if kind_value not in {"food","drink","beverage"}:
                        bulk_errors.append(f"Row {row_num}: product_type must be Food or Drink.")
                    category_key=next((category for category in INTERNAL_THRESHOLDS if category.casefold()==category_value.casefold()),None)
                    if not category_key:
                        bulk_errors.append(f"Row {row_num}: choose an internal threshold category from the valid category list.")
                    else:
                        bulk_df.at[row_index,"internal_threshold_category"]=category_key
                if "sku_id" in bulk_df:
                    sku_values=bulk_df["sku_id"].astype(str).str.strip()
                    duplicated=sku_values[sku_values.ne("") & sku_values.duplicated(keep=False)]
                    if not duplicated.empty:
                        bulk_errors.append("SKU IDs must be unique within the file: "+", ".join(sorted(set(duplicated.tolist()))))
            st.dataframe(bulk_df.head(10),hide_index=True,use_container_width=True)
        except Exception as exc:
            bulk_errors.append(f"Could not read the CSV: {exc}")
        if bulk_errors:
            for message in bulk_errors: st.error(message)
        else:
            st.success(f"{len(bulk_df)} SKU row(s) ready.")
            if st.button("Calculate both NPM models and create PDFs",type="primary",key="run_bulk_assessment"):
                generated=[]
                timestamp=datetime.now(timezone.utc).isoformat()
                try:
                    for index,row in bulk_df.iterrows():
                        record,filename=bulk_row_to_record(row.to_dict(),index,timestamp,bulk_reviewer)
                        pdf_bytes=build_assessment_pdf(record)
                        generated.append({"record":record,"filename":filename,"pdf":pdf_bytes})
                except ModuleNotFoundError as exc:
                    if exc.name and exc.name.startswith("reportlab"):
                        st.error('PDF export needs reportlab. Add "reportlab" to the dependencies in pyproject.toml and redeploy.')
                    else:
                        raise
                else:
                    st.session_state["bulk_pdf_outputs"]=generated
                    st.session_state["bulk_source_hash"]=bulk_source_hash
                    st.session_state["bulk_reviewer_for_outputs"]=bulk_reviewer
    outputs=st.session_state.get("bulk_pdf_outputs",[])
    if outputs and bulk_source_hash==st.session_state.get("bulk_source_hash"):
        st.markdown("### Reports")
        zip_buffer=BytesIO()
        with ZipFile(zip_buffer,"w",compression=ZIP_DEFLATED) as archive:
            for output in outputs:
                archive.writestr(output["filename"],output["pdf"])
        st.download_button("Download all PDFs · ZIP",zip_buffer.getvalue(),file_name="nutrition-bulk-assessments.zip",mime="application/zip",key="bulk_zip_download")
        for index,output in enumerate(outputs):
            record=output["record"]
            input_data=record["inputs"]
            results=record["results"]
            statuses=[f"{NPM[result['model']]['id']}: {('blocked' if result['blocked'] else result['classification'])}" for result in results]
            st.download_button(f"Download {output['filename']}",output["pdf"],file_name=output["filename"],mime="application/pdf",key=f"bulk_pdf_{index}")
            st.caption(f"{input_data['sku']} · {input_data['name']} — {'; '.join(statuses)}")
            prompt_matches=record.get("ingredientPromptMatches",[])
            with st.expander(f"Ingredient review · {input_data['sku']} · {len(prompt_matches)} match(es)"):
                if prompt_matches:
                    st.dataframe(pd.DataFrame(prompt_matches).rename(columns={"reviewArea":"Review area","matchedIngredient":"Ingredient text (as entered)","matchedText":"Matched text","searchTerm":"Search term"}),hide_index=True,use_container_width=True)
                    st.caption("Review each match against the controlled additive policy.")
                elif input_data.get("ingredients"):
                    st.caption("No prototype keyword prompts found. This does not confirm compliance.")
                else:
                    st.caption("No ingredient declaration was provided; keyword review was not run.")

with scope:
    st.markdown("## A considered category estimate")
    st.markdown('<div class="leaf-note">This optional AI estimate suggests a category only. It does not calculate NPM or determine legal HFSS status. Product facts and any context you supply are sent to OpenAI when you choose to run it.</div>',unsafe_allow_html=True)
    a,b=st.columns(2)
    with a:
        occasion=st.text_input("Intended eating occasion",placeholder="e.g. snack, meal component")
        form=st.text_input("Product form and preparation",placeholder="e.g. ready to eat, powder reconstituted")
        portion=st.text_input("Pack / portion detail",placeholder="e.g. 40 g single serve")
        description=st.text_area("Product / marketing description",height=100)
        context=st.text_area("Optional category guidance or context",height=130)
    with b:
        model=st.text_input("Approved OpenAI model ID",placeholder="Your organisation-approved model ID")
        api_key=st.text_input("OpenAI API key",type="password",help="Used only for this request; not written into the assessment record.")
        consent=st.checkbox("I understand that product details and context will be sent for the AI estimate.")
        run_ai=st.button("Estimate category with AI",type="primary")
        st.caption("The output requires human review. The API key is not exported or saved by this app.")
    permitted=["1 | Prepared soft drinks with added sugar","2 | Savoury snacks","3 | Breakfast cereals","4 | Confectionery","5 | Ice cream and similar frozen products","6 | Cakes and cupcakes","7 | Sweet biscuits and nut, seed or cereal bars","8 | Morning goods","9 | Desserts and puddings","10 | Sweetened yoghurt and fromage frais","11 | Pizza","12 | Potato products","13 | Ready meals and meal centres","not determined"]
    facts={"sku":sku,"name":name,"product_type":kind,"assessment_basis":basis,"retailer_categories":[l1,l2,l3,l4],"eating_occasion":occasion,"form_and_preparation":form,"pack_portion":portion,"description":description,"ingredients":ingredients}
    if run_ai:
        if not api_key or not model or not consent: st.error("Enter an approved model ID and API key, then confirm data transmission.")
        else:
            prompt=f'''You are a UK HFSS product category classifier. Classify only into one permitted category or "not determined". Copy the category exactly. Retailer categories are supporting evidence only. Do not calculate NPM or determine legal HFSS status. Provide concise evidence based only on supplied facts. Return JSON with suggested_category, confidence, evidence_rationale (array of product_fact and why_it_supports_category), alternative_categories (array of category and why_rejected), missing_information (array), limitations. Permitted categories: {json.dumps(permitted)}. Product facts: {json.dumps(facts)}. Additional context: {context}'''
            try:
                import requests
                response=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},json={"model":model,"store":False,"input":prompt},timeout=60); response.raise_for_status(); payload=response.json(); raw=payload.get("output_text","")
                if not raw:
                    raw="".join(c.get("text","") for item in payload.get("output",[]) for c in item.get("content",[]))
                result=json.loads(re.sub(r"^```json\s*|\s*```$","",raw.strip(),flags=re.I))
                category=result.get("suggested_category","not determined")
                if category not in permitted: category="not determined"
                st.session_state["ai_result"]={**result,"suggested_category":category}
            except Exception as e: st.error(f"The category estimate did not complete: {e}")
    if st.session_state.get("ai_result"):
        res=st.session_state["ai_result"]; st.markdown("### Suggested category"); st.success(f"{res['suggested_category']} · confidence: {res.get('confidence','not supplied')}")
        st.markdown("**Evidence**"); st.write(res.get("evidence_rationale",[])); st.markdown("**Alternative categories considered**"); st.write(res.get("alternative_categories",[])); st.markdown("**Missing information**"); st.write(res.get("missing_information",[])); st.caption(res.get("limitations","Human review required."))

with policy:
    st.markdown("## Nutrition references")
    st.markdown('<div class="amber-note"><b>Reference only.</b> Transcribed from a supplied threshold table. The source notes unresolved units, category mapping and interpretation. These values do not feed the NPM calculations and are not approved pass/fail criteria.</div>',unsafe_allow_html=True)
    global_policy={"Banana and plantain chips":"Total sugars ≤15 g; saturated fat ≤19 g","Bread substitutes":"Saturated fat ≤2.8 g; fibre ≥3 g; salt ≤1.2 g","Breakfast cereals":"Total sugars ≤16 g; saturated fat ≤2.8 g; fibre ≥6 g; salt ≤0.9 g","Broths":"Salt ≤0.59 g","Brown bread":"Fibre >10 g; salt ≤1.08 g","Cakes":"Total sugars ≤15 g; saturated fat ≤11 g; salt ≤0.66 g","Chewing gum and mints":"No added sugar","Chips / crisps":"Saturated fat ≤3 g; salt ≤1.1 g","Chocolate spread":"Total sugars ≤15 g; saturated fat ≤9 g","Cold tomato / vegetable sauces":"Total sugars ≤16 g; salt ≤1.63 g","Cookies":"Total sugars ≤18 g; saturated fat ≤11 g; salt ≤0.76 g","Dairy and plant-based drinks":"Total sugars ≤4.5 g","Emulsion-based sauces":"Salt ≤1 g","Fruit and vegetable juices":"No added sugar","Grain, muesli, fruit and energy bars":"Total sugars ≤20 g; saturated fat ≤5 g; salt ≤0.4 g","Hot beverages":"Total sugars ≤4.5 g","Meat substitutes":"Saturated fat ≤18.1 g; salt ≤1.3 g","Nut-based spreads":"Total sugars ≤10 g; saturated fat ≤6 g; salt ≤0.84 g","Other savoury snacks":"Saturated fat ≤2.5 g; salt ≤1.5 g","Other savoury spreads":"Saturated fat ≤2.5 g; salt ≤1.1 g","Protein bar":"Total sugars ≤20 g; saturated fat ≤5 g; fibre ≥6 g; salt ≤0.8 g","Salted nuts and seeds":"Salt ≤1.2 g","Soft drinks, energy drinks and prepared syrups":"Total sugars ≤4.5 g","Soups":"Salt ≤0.59 g","Sweet spreads":"Total sugars ≤27 g","Sweets":"Total sugars ≤15 g","Warm tomato / vegetable sauces":"Salt ≤1.1 g","Chocolate":"Total sugars ≤30 g"}
    aspirational={"Breakfast cereals":"Protein energy ≥12%; fibre ≥6 g; plant points ≥5","Cakes":"Fibre >6 g; plant points >4","Chips":"Fibre >6 g; plant points >1","Chocolate":"Fibre ≥10 g; plant points ≥2","Cookies":"Fibre ≥6 g; protein ≥8 g; plant points ≥5","Grain, muesli, fruit and energy bars":"Fibre ≥6 g; protein ≥8 g; plant points ≥5","Nut-based spreads":"Fibre ≥6 g; protein ≥10 g; plant points ≥3","Protein bar":"Protein ≥20 g; fibre ≥8 g; plant points ≥4","Soft drinks, energy drinks and prepared syrups":"Plant points ≥1","Soups":"Fibre ≥3 g; protein ≥3 g; plant points ≥5","Sweet spreads":"Fibre ≥6 g; protein ≥10 g; plant points ≥5","Warm tomato / vegetable sauces":"Plant points ≥3","Brown bread":"Fibre >10 g; plant points >5","Salted nuts and seeds":"Plant points ≥5","Other savoury spreads":"Fibre ≥6 g; plant points ≥3","Other savoury snacks":"Plant points ≥3"}
    st.markdown("### Current nutrition thresholds · reference"); st.dataframe(pd.DataFrame([{"Product family":k,"Thresholds per 100":v} for k,v in global_policy.items()]),hide_index=True,use_container_width=True)
    st.markdown("### Own-brand aspirational criteria · reference"); st.dataframe(pd.DataFrame([{"Product family":k,"Criteria per 100":v} for k,v in aspirational.items()]),hide_index=True,use_container_width=True)

with audit:
    st.markdown("## Calculation logic & audit")
    st.markdown("The calculation is deterministic. The same entered values and rules produce the same score. This page exposes the rules encoded in this app and the trace from the last calculation.")
    st.markdown("**Scoring sequence**")
    st.markdown("1. Score each A nutrient against its point cut-offs and add the points.\n2. Score each C component and check the protein gate.\n3. Calculate `final score = total A points - eligible C points`.\n4. Compare the score with the selected product-type threshold: food ≥ 4; drink ≥ 1.")
    st.markdown("The app counts a point when a value is **strictly greater than** a cut-off. A value exactly on a cut-off does not pass it. The 2004/05 model derives sodium as entered salt × 400. For NPM 2018, the app requires AOAC fibre and uses entered free sugars and FVNS; it does not derive these from ingredients.")
    st.markdown("### Point bands encoded in the app")
    for model_key in ("2004/05","2018"):
        a_table,c_table=point_band_tables(model_key)
        with st.expander(f"{NPM[model_key]['label']} · show all point bands",expanded=(model_key=="2004/05")):
            st.markdown("**A points**")
            st.dataframe(a_table,hide_index=True,use_container_width=True)
            st.markdown("**C points**")
            st.dataframe(c_table,hide_index=True,use_container_width=True)
    st.caption("The band tables above are generated from the threshold arrays in `app.py`. `Not applicable` marks point levels that the model does not award for that component.")
    st.markdown("### Last calculation trace")
    audit_run=st.session_state.get("assessment_run")
    if not audit_run:
        st.info("Run a calculation on Product assessment to populate the case-specific trace.")
    else:
        try: run_display=datetime.fromisoformat(audit_run["timestamp"]).astimezone().strftime("%d %b %Y, %H:%M %Z")
        except (ValueError,TypeError): run_display=audit_run["timestamp"]
        ai=audit_run["inputs"]
        st.caption(f"Run: {run_display} · Product ID: {ai.get('sku') or 'Not provided'} · Product: {ai.get('name') or 'Not provided'} · Type: {ai.get('product_type')} · Basis: {ai.get('assessment_basis')} · Ruleset: 2026-09-10 v0.1 · {audit_run['source']}")
        with st.expander("Inputs used for this run",expanded=True):
            input_rows=[("Energy",ai.get("energy"),"kJ / 100"),("Saturated fat",ai.get("sat"),"g / 100"),("Total sugars",ai.get("sugar"),"g / 100"),("Free sugars",ai.get("freeSugar"),"g / 100"),("Salt",ai.get("salt"),"g / 100"),("Derived sodium",ai.get("sodium"),"mg / 100"),("Protein",ai.get("protein"),"g / 100"),("Fibre",ai.get("fibre"),f"g / 100 · {ai.get('fibreMethod')}"),("FVN",ai.get("fvn"),"%"),("FVNS",ai.get("fvns"),"%"),("Nutrition source",ai.get("nutrition_source"),""),("Specialist data source",ai.get("specialist_source"),"")]
            st.dataframe(pd.DataFrame([{"Input":label,"Value":"Not entered" if val is None else val,"Unit / note":unit} for label,val,unit in input_rows]),hide_index=True,use_container_width=True)
        for result in audit_run["results"]:
            with st.expander(f"{NPM[result['model']]['label']} · {'Blocked' if result['blocked'] else result['classification']}",expanded=True):
                if result["blocked"]:
                    st.error("No score produced. Missing or invalid: " + ", ".join(result["missing"]))
                else:
                    a_rows=[row for row in result["ledger"] if row["Group"]=="A"]
                    c_rows=[row for row in result["ledger"] if row["Group"]=="C"]
                    fv_row=next(row for row in c_rows if row["Input"].startswith("FVN"))
                    fibre_row=next(row for row in c_rows if row["Input"].startswith("Fibre"))
                    protein_row=next(row for row in c_rows if row["Input"].startswith("Protein"))
                    st.markdown(f"**Step 1 - A points:** {' + '.join(str(row['Points']) for row in a_rows)} = **{result['A']}**")
                    st.dataframe(pd.DataFrame(a_rows),hide_index=True,use_container_width=True)
                    st.markdown(f"**Step 2 - C points:** FVN/FVNS {fv_row['Points']} + fibre {fibre_row['Points']} + protein {protein_row['Points'] if result['protein_used'] else 0} = **{result['C']}**")
                    if result["A"]>=11 and fv_row["Points"]<5:
                        st.caption(f"Protein gate: A = {result['A']} (≥ 11) and {fv_row['Input']} points = {fv_row['Points']} (< 5), so protein points are excluded.")
                    else:
                        st.caption(f"Protein gate: {'protein points are included' if result['protein_used'] else 'protein points are excluded'} for this case.")
                    st.dataframe(pd.DataFrame(c_rows),hide_index=True,use_container_width=True)
                    operator="≥" if result["classification"]=="Less healthy" else "<"
                    st.markdown(f"**Step 3 - Final score:** A {result['A']} − C {result['C']} = **{result['score']}**.")
                    st.markdown(f"**Step 4 - Classification:** {result['score']} {operator} {result['threshold']} {('drink' if ai.get('product_type')=='Drink' else 'food')} threshold → **{result['classification']}**.")
                    st.caption(result["notes"])
    st.markdown("### Method references")
    st.markdown("- [NPM 2004/05 technical guidance (Department of Health, 2011)](https://assets.publishing.service.gov.uk/media/695e87982a4a53b73d513855/NutrientProfilingModel_2004_2005_TechnicalGuidance.pdf)\n- [NPM 2018 technical guidance (Department of Health and Social Care)](https://www.gov.uk/government/publications/nutrient-profiling-model-2018/nutrient-profiling-model-2018-technical-guidance)\n- [NPM 2018 publication status](https://www.gov.uk/government/publications/nutrient-profiling-model-2018): the published guidance describes NPM 2018 as a reference model not yet applied to policy.")
    st.warning("This audit view shows what this app calculated from the supplied inputs. It is not an independent validation of source data or regulatory interpretation. Have the formula tables, category decisions and evidence requirements reviewed against the current controlled guidance before relying on a result.")

with guide:
    st.markdown("## A little guidance before you begin")
    st.markdown("### How to get a useful assessment")
    st.markdown("- Enter nutrition values per 100 g for foods or per 100 ml for drinks. Use supplier or laboratory specification values rather than rounded pack serving values.\n- For reconstituted products, assess the values after preparation using the manufacturer’s instructions.\n- NPM 2004/05 needs total sugars and FVN. NPM 2018 needs verified free sugars and FVNS, and uses AOAC fibre. Missing evidence blocks that model’s result.\n- The NPM 2018 result is shown as a comparison / future-readiness scenario until its business application is confirmed.")
    st.markdown("### Reading the results")
    st.markdown("The score is A points minus C points. Food is classified as less healthy at a score of 4 or more; drinks at 1 or more. Protein points are excluded when A points are at least 11 and FVN/FVNS points are below 5. The ledger shows each value, threshold, point total and gate decision.")
    st.markdown("### What this tool does not decide")
    st.markdown("NPM classification alone does not establish whether a product is legally in scope of HFSS restrictions. The AI category estimate is optional and requires human review. Ingredient keyword prompts are not an additive policy screen, and a missing keyword match is not confirmation of compliance. Do not use the threshold references as approved pass/fail criteria.")
    st.markdown("### Ingredient review prompts")
    st.caption("A lightweight keyword prompt only. It does not determine compliance or replace the controlled additive policy.")
    st.dataframe(pd.DataFrame([{"Review area":label,"Terms scanned":", ".join(terms)} for label,terms in INGREDIENT_REVIEW_PROMPTS]),hide_index=True,use_container_width=True)
    st.caption("The scan is case-insensitive. BHA and BHT are matched as whole words. To change what it checks, edit `INGREDIENT_REVIEW_PROMPTS` in app.py; the table, single and bulk runs use the same list.")
    ingredient_text=st.text_area("Ingredient declaration to review",value=ingredients,key="ingredient_screen",height=110)
    if st.button("Scan for review prompts"):
        matches=scan_ingredient_review(ingredient_text)
        if not ingredient_text.strip(): st.warning("Paste an ingredient declaration first.")
        elif matches:
            st.warning(f"{len(matches)} keyword match(es) found. Check each against the controlled additive policy and technical function.")
            st.dataframe(pd.DataFrame(matches).rename(columns={"reviewArea":"Review area","matchedIngredient":"Ingredient text (as entered)","matchedText":"Matched text","searchTerm":"Search term"}),hide_index=True,use_container_width=True)
        else: st.success("No prototype keyword prompts found. This does not confirm policy compliance.")
    st.markdown('<div class="leaf-note">Use this as a transparent working aid. Regulatory interpretation, evidence quality and final product decisions remain with qualified reviewers.</div>',unsafe_allow_html=True)

st.markdown("<div style='text-align:center;color:#819087;font-size:.8rem;margin-top:2rem'>A thoughtful working aid · Deterministic NPM scoring · Ruleset build 10 September 2026 · v0.1</div>",unsafe_allow_html=True)
