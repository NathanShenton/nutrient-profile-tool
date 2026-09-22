"""Nutrition product assessment — Streamlit edition.

Run with: streamlit run app.py
Calculations are a transparent working aid and do not replace expert or regulatory sign-off.
"""
from __future__ import annotations

import json
import re
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Nutrition, thoughtfully", page_icon="🌿", layout="wide")
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
<div class="hero"><div class="eyebrow">Nutrition product assessment</div>
<h1>Nutrition Product Tool</h1>
<p>Calculate NPM scores, review the inputs and record product evidence.</p></div>
""", unsafe_allow_html=True)

NPM = {
    "2004/05": dict(id="NPM 2004/05", label="NPM 2004/05 · regulatory calculation",
        a=[("Energy (kJ)","energy",[335,670,1005,1340,1675,2010,2345,2680,3015,3350]),("Saturated fat (g)","sat",[1,2,3,4,5,6,7,8,9,10]),("Total sugars (g)","sugar",[4.5,9,13.5,18,22.5,27,31,36,40,45]),("Sodium (mg)","sodium",[90,180,270,360,450,540,630,720,810,900])], fibre={"NSP / Englyst":[.7,1.4,2.1,2.8,3.5],"AOAC":[.9,1.9,2.8,3.7,4.7]}, protein=[1.6,3.2,4.8,6.4,8], fv="fvn"),
    "2018": dict(id="NPM 2018", label="NPM 2018 · scenario / future-readiness", a=[("Energy (kJ)","energy",[315,630,945,1260,1575,1890,2205,2520,2835,3150]),("Saturated fat (g)","sat",[.9,1.9,2.8,3.7,4.7,5.6,6.6,7.5,8.4,9.4]),("Free sugars (g)","freeSugar",[.9,1.9,2.8,3.7,4.6,5.6,6.5,7.4,8.3,9.3]),("Salt (g)","salt",[.2,.5,.7,.9,1.1,1.4,1.6,1.8,2,2.3])], fibre={"AOAC":[.6,1.2,1.8,2.4,3,3.6,4.2,4.8,5.4,6]}, protein=[1.7,3.4,5.1,6.8,8.5], fv="fvns")
}

# Transcribed current H&B threshold reference from the supplied prototype.
# These are comparisons against entered values, not a governed compliance decision.
HB_THRESHOLDS = {
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
HB_METRIC_LABELS = {"sugar":"Total sugars", "sat":"Saturated fat", "salt":"Salt", "fibre":"Fibre", "protein":"Protein", "plantPoints":"Plant points", "proteinEnergyPct":"Energy from protein"}


def check_hb_thresholds(category: str, x: dict, added_sugar: str) -> list[dict]:
    values={"sugar":x.get("sugar"),"sat":x.get("sat"),"salt":x.get("salt"),"fibre":x.get("fibre"),"protein":x.get("protein"),"plantPoints":x.get("plantPoints"),"proteinEnergyPct":x.get("proteinEnergyPct")}
    rows=[]
    for key,operator,target in HB_THRESHOLDS[category]:
        label="Added-sugar status" if key=="addedSugarStatus" else HB_METRIC_LABELS[key]
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
        [para("REVIEW DECISION","MetaLabel"),para(inp.get("review_decision")),para("RULESET","MetaLabel"),para(record.get("rulesetBuild"))],
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
    sku=st.text_input("SKU ID",placeholder="e.g. HB-10482")
    name=st.text_input("Product name",placeholder="e.g. Berry oat bar")
    kind=st.selectbox("Product type",["Food","Drink"])
    basis=st.selectbox("Assessment basis",["As sold","Reconstituted to pack instructions"])
    st.markdown("---")
    st.caption("Reference values only. Reconstituted products should use values after preparation as directed.")

assessment, scope, policy, guide = st.tabs(["✦  Product assessment","✧  Category estimate","❋  H&B thresholds","♡  Guide & controls"])
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
            with c2: plant=st.number_input("Plant points · H&B policy input",min_value=0,value=None,step=1); protein_pct=st.number_input("Energy from protein · %",min_value=0.0,max_value=100.0,value=None,step=.1)
            st.markdown('<div class="amber-note">FVN, FVNS and free sugars must not be inferred from an ingredient list alone. Missing verified values block the relevant model.</div>',unsafe_allow_html=True)
            calc=st.button("Calculate both NPM models",type="primary",use_container_width=True)
            example=st.button("Load worked 2004/05 example")
    x={"energy":energy,"sat":sat,"sugar":sugar,"salt":salt,"sodium":salt*400 if salt is not None else None,"protein":protein,"fibre":fibre,"freeSugar":free_sugar,"fvn":fvn,"fvns":fvns,"fibreMethod":fibre_method,"plantPoints":plant,"proteinEnergyPct":protein_pct}
    if example:
        x.update(dict(energy=459,sat=1.8,sugar=13.4,salt=.00025,sodium=.1,protein=6.5,fibre=.6,fvn=8,fvns=None,freeSugar=None,fibreMethod="AOAC"))
        st.session_state["demo_result"]=[score_model(m,x,"Food") for m in NPM]
    if calc: st.session_state["assessment_result"]=[score_model(m,x,kind) for m in NPM]
    with right:
        st.markdown("### Your NPM results")
        st.caption("Both models run together. NPM 2018 remains a comparison scenario until its business application is confirmed.")
        results=st.session_state.get("assessment_result") or st.session_state.get("demo_result")
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
        st.markdown("### H&B threshold check")
        st.caption("Choose a product category to compare its entered nutrient values with the reference thresholds.")
        hb_category=st.selectbox("H&B threshold category",list(HB_THRESHOLDS),key="hb_threshold_category")
        run_hb_check=st.button("Check selected threshold",key="run_hb_check",use_container_width=True)
        hb_inputs={**x,"addedSugarStatus":added}
        if run_hb_check:
            st.session_state["hb_check_result"]={"category":hb_category,"inputs":hb_inputs,"rows":check_hb_thresholds(hb_category,x,added)}
        saved_hb=st.session_state.get("hb_check_result")
        if saved_hb:
            if saved_hb["category"]!=hb_category or saved_hb["inputs"]!=hb_inputs:
                st.info("Product values or category have changed since the last check. Run the check again.")
            else:
                failed=[row["Nutrient / criterion"] for row in saved_hb["rows"] if row["Status"]=="FAIL"]
                pending=[row["Nutrient / criterion"] for row in saved_hb["rows"] if row["Status"]=="PENDING"]
                if failed: st.error("Outside selected threshold: " + ", ".join(failed))
                elif pending: st.warning("Check incomplete. Add or confirm: " + ", ".join(pending))
                else: st.success("All checked criteria are within the selected thresholds.")
                st.dataframe(pd.DataFrame(saved_hb["rows"]),hide_index=True,use_container_width=True)
                st.caption("Reference comparison only; confirm thresholds against the current controlled H&B policy before making a product decision.")
        if results:
            record={"timestamp":datetime.now(timezone.utc).isoformat(),"rulesetBuild":"2026-09-10 v0.1","inputs":{"sku":sku,"name":name,"product_type":kind,"assessment_basis":basis,"l1":l1,"l2":l2,"l3":l3,"l4":l4,"ingredients":ingredients,"reviewer":reviewer,"review_decision":decision,"review_notes":review_notes,"nutrition_source":nutrition_source,"specialist_source":specialist_source,**x},"results":results}
            safe_sku=re.sub(r'[^a-zA-Z0-9_-]','-',sku or 'draft')
            json_col,pdf_col=st.columns(2)
            with json_col:
                st.download_button("Download assessment record · JSON",json.dumps(record,indent=2),file_name=f"nutrition-assessment-{safe_sku}.json",mime="application/json",use_container_width=True)
            with pdf_col:
                st.download_button("Download assessment report · PDF",build_assessment_pdf(record),file_name=f"nutrition-assessment-{safe_sku}.pdf",mime="application/pdf",use_container_width=True)

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
    st.markdown("## Holland & Barrett nutrition references")
    st.markdown('<div class="amber-note"><b>Reference only.</b> Transcribed from the source prototype’s H&B threshold table. The source notes unresolved units, category mapping and interpretation. These values do not feed the NPM calculations and are not approved pass/fail criteria.</div>',unsafe_allow_html=True)
    global_policy={"Banana and plantain chips":"Total sugars ≤15 g; saturated fat ≤19 g","Bread substitutes":"Saturated fat ≤2.8 g; fibre ≥3 g; salt ≤1.2 g","Breakfast cereals":"Total sugars ≤16 g; saturated fat ≤2.8 g; fibre ≥6 g; salt ≤0.9 g","Broths":"Salt ≤0.59 g","Brown bread":"Fibre >10 g; salt ≤1.08 g","Cakes":"Total sugars ≤15 g; saturated fat ≤11 g; salt ≤0.66 g","Chewing gum and mints":"No added sugar","Chips / crisps":"Saturated fat ≤3 g; salt ≤1.1 g","Chocolate spread":"Total sugars ≤15 g; saturated fat ≤9 g","Cold tomato / vegetable sauces":"Total sugars ≤16 g; salt ≤1.63 g","Cookies":"Total sugars ≤18 g; saturated fat ≤11 g; salt ≤0.76 g","Dairy and plant-based drinks":"Total sugars ≤4.5 g","Emulsion-based sauces":"Salt ≤1 g","Fruit and vegetable juices":"No added sugar","Grain, muesli, fruit and energy bars":"Total sugars ≤20 g; saturated fat ≤5 g; salt ≤0.4 g","Hot beverages":"Total sugars ≤4.5 g","Meat substitutes":"Saturated fat ≤18.1 g; salt ≤1.3 g","Nut-based spreads":"Total sugars ≤10 g; saturated fat ≤6 g; salt ≤0.84 g","Other savoury snacks":"Saturated fat ≤2.5 g; salt ≤1.5 g","Other savoury spreads":"Saturated fat ≤2.5 g; salt ≤1.1 g","Protein bar":"Total sugars ≤20 g; saturated fat ≤5 g; fibre ≥6 g; salt ≤0.8 g","Salted nuts and seeds":"Salt ≤1.2 g","Soft drinks, energy drinks and prepared syrups":"Total sugars ≤4.5 g","Soups":"Salt ≤0.59 g","Sweet spreads":"Total sugars ≤27 g","Sweets":"Total sugars ≤15 g","Warm tomato / vegetable sauces":"Salt ≤1.1 g","Chocolate":"Total sugars ≤30 g"}
    aspirational={"Breakfast cereals":"Protein energy ≥12%; fibre ≥6 g; plant points ≥5","Cakes":"Fibre >6 g; plant points >4","Chips":"Fibre >6 g; plant points >1","Chocolate":"Fibre ≥10 g; plant points ≥2","Cookies":"Fibre ≥6 g; protein ≥8 g; plant points ≥5","Grain, muesli, fruit and energy bars":"Fibre ≥6 g; protein ≥8 g; plant points ≥5","Nut-based spreads":"Fibre ≥6 g; protein ≥10 g; plant points ≥3","Protein bar":"Protein ≥20 g; fibre ≥8 g; plant points ≥4","Soft drinks, energy drinks and prepared syrups":"Plant points ≥1","Soups":"Fibre ≥3 g; protein ≥3 g; plant points ≥5","Sweet spreads":"Fibre ≥6 g; protein ≥10 g; plant points ≥5","Warm tomato / vegetable sauces":"Plant points ≥3","Brown bread":"Fibre >10 g; plant points >5","Salted nuts and seeds":"Plant points ≥5","Other savoury spreads":"Fibre ≥6 g; plant points ≥3","Other savoury snacks":"Plant points ≥3"}
    st.markdown("### Current nutrition thresholds · reference"); st.dataframe(pd.DataFrame([{"Product family":k,"Thresholds per 100":v} for k,v in global_policy.items()]),hide_index=True,use_container_width=True)
    st.markdown("### Own-brand aspirational criteria · reference"); st.dataframe(pd.DataFrame([{"Product family":k,"Criteria per 100":v} for k,v in aspirational.items()]),hide_index=True,use_container_width=True)

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
    ingredient_text=st.text_area("Ingredient declaration to review",value=ingredients,key="ingredient_screen",height=110)
    if st.button("Scan for review prompts"):
        groups=[("Benzoates",r"benzoate|benzoic acid"),("Nitrites and nitrates",r"nitrite|nitrate"),("Phosphates and chelating agents",r"phosphate|phosphoric acid|edta|ethylenediaminetetraacetic"),("Synthetic antioxidant review",r"\bbha\b|\bbht\b|tbhq|propyl gallate"),("Emulsifier review",r"emulsifier|mono[- ]?and diglyceride|polysorbate"),("Artificial sweetener review",r"aspartame|acesulfame|saccharin|cyclamate|sucralose"),("Artificial colour review",r"artificial colou?r|tartrazine|sunset yellow|quinoline yellow|allura red"),("Processing-aid review",r"processing aid")]
        text=ingredient_text.lower()
        hits=[label for label,pattern in groups if re.search(pattern,text)]
        if not text.strip(): st.warning("Paste an ingredient declaration first.")
        elif hits:
            st.warning(f"{len(hits)} review prompt(s) found. Check each against the controlled additive policy and technical function.")
            for hit in hits: st.write("• " + hit)
        else: st.success("No prototype keyword prompts found. This does not confirm policy compliance.")
    st.markdown('<div class="leaf-note">Use this as a transparent working aid. Regulatory interpretation, evidence quality and final product decisions remain with qualified reviewers.</div>',unsafe_allow_html=True)

st.markdown("<div style='text-align:center;color:#819087;font-size:.8rem;margin-top:2rem'>A thoughtful working aid · Deterministic NPM scoring · Ruleset build 10 September 2026 · v0.1</div>",unsafe_allow_html=True)
