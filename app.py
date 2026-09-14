import streamlit as st
import google.generativeai as genai
import PyPDF2
import json
import time   
import random 
import csv 
import io
import os
import subprocess # Tambah module ini
from datetime import datetime

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="C* Datasheet Analyzer", page_icon="📄", layout="wide")
st.title("📄 C* Datasheet Analyzer")
st.write("Upload a datasheet (PDF) and the AI will extract the key specifications.")

# --- AUTO-UPDATE DATE LOGIC ---
def get_last_update_date(file_path):
    try:
        # Check Git history for the last actual commit date of this file
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%cd', '--date=format:%d/%m/%Y', file_path],
            capture_output=True, text=True, check=True
        )
        git_date = result.stdout.strip()
        if git_date:
            return git_date
    except Exception:
        pass # Ignore errors if Git isn't initialized or fails
        
    # Fallback to OS file timestamp if Git is unavailable
    modified_timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(modified_timestamp).strftime("%d/%m/%Y")

file_path = __file__
last_update_date = get_last_update_date(file_path)
st.write(f"Analyzer last update on: {last_update_date}.")

# --- 2. INISIALISASI MEMORI (SESSION STATE) ---
if "reset_key" not in st.session_state:
    st.session_state.reset_key = 0
if "history" not in st.session_state:
    st.session_state.history = []

# --- PAPARAN HISTORY DI SIDEBAR ---
with st.sidebar:
    st.header("🕰️ Extraction History")
    if st.session_state.history:
        for idx, item in enumerate(reversed(st.session_state.history)):
            st.write(f"• {item}")
        
        if st.button("🗑️ Clear History"):
            st.session_state.history = []
            st.rerun() 
    else:
        st.info("No search record yet.")
  
# --- 3 & 4. BUTANG RESET, INPUT MPN & UPLOAD ---
if st.button("🔄 Reset"):
    st.session_state.reset_key += 1
    st.rerun() 

target_mpn = st.text_input("Enter specific MPN (Optional but recommended for catalogs):", key=f"mpn_{st.session_state.reset_key}")

col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader("1. Upload Datasheet PDF (General)", type=["pdf"], key=f"pdf_{st.session_state.reset_key}")
with col2:
    spec_file = st.file_uploader("2. Upload Spec Sheet PDF (Optional - Priority)", type=["pdf"], key=f"spec_{st.session_state.reset_key}")

if uploaded_file is not None or spec_file is not None:
    if st.button("Extract Data", type="primary"):
        progress_text = "Starting extraction process..."
        progress_bar = st.progress(0, text=progress_text)
        
        try:
            pdf_text = ""
            
            # --- BACA SPEC SHEET DAHULU (JIKA ADA) ---
            if spec_file is not None:
                spec_reader = PyPDF2.PdfReader(spec_file)
                if spec_reader.is_encrypted:
                    try: spec_reader.decrypt("")
                    except Exception: pass
                spec_text = "".join([page.extract_text() for page in spec_reader.pages if page.extract_text()])
                pdf_text += f"\n\n=== CRITICAL PRIORITY: SPECIFIC SPEC SHEET ===\n{spec_text}\n\n=== GENERAL DATASHEET ===\n"
            
            # --- BACA DATASHEET SEPERTI BIASA ---
            if uploaded_file is not None:
                reader = PyPDF2.PdfReader(uploaded_file)
                if reader.is_encrypted:
                    try:
                        reader.decrypt("")
                    except Exception:
                        st.error("General PDF file is encrypted with Password. Please find un-encrypted PDF.")
                        st.stop()
                
                total_pages = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text:
                        pdf_text += f"\n\n--- PAGE {i + 1} ---\n{text}"
                    prog_val = int(((i + 1) / total_pages) * 30)
                    progress_bar.progress(prog_val, text=f"Reading PDF... (Page {i+1}/{total_pages})")
            else:
                progress_bar.progress(30, text="Reading Spec Sheet PDF...")
            
            mpn_instruction = f"Focus ONLY on the specifications for this specific MPN: {target_mpn}." if target_mpn else "Extract the general specifications from the datasheet."
            
            full_prompt = f"""
            Act as an expert electronics engineer. {mpn_instruction}
            Review the provided capacitor datasheet text and accurately extract the requested information. 
            
            Extract these exact keys:
            "Commodity Group", "Catalogue Group", "Manufacturer", "Designation",
            "Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", 
            "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)", 
            "Length [mm]", "Width [mm]", "Height [mm]", "Height (Max)", "Package Type", "Package Type (EIA)", 
            "Pitch_Calculation_Logic", "Pitch (Footprint) (mm)",
            "Capacity [F]", "Tolerance [%]", "Voltage [V]", "Description", "Surface", "Additional Information",
            "Function", "Attenuation [dB]", "f Nom. (Typ) [Hz]", "Current [A]", "Inductance [H]",
            "ImpMax [Ohm]", "Insertion Loss (Max) [dB]", "Filter Type", "Resistance [Ohm]",
            "Impedance@MHz", "ImpMax@MHz [Hz]", "Ripple Current", "Processing Technology", 
            "ESR [Ohm]", "Endurance [h/°C]",
            "Kind of Mounting", "Washability", "Varnishability", "St. Solder (Standard Solder)", 
            "Alt. Solder (Alternate Solder)", "Rep. Solder (Repair Solder)", "ESS Suitable", 
            "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)", "Number of Pins"

            Important Instructions:
            - Return strictly a valid JSON object.
            - Do NOT use unescaped double quotes (") inside any text values. Use single quotes (') instead.
            - Do NOT include raw newline characters (\\n), carriage returns (\\r), or tabs (\\t).
            - FOR ALL KEYS: Return a nested JSON object with three fields: "value", "evidence", and "page".
            - CRITICAL: If any information is missing or not found in the datasheet, strictly return "N/A" for the "value", "evidence", and "page" fields. Do NOT return null, None, or "unknown".

          [CAPACITOR SPECIFIC RULES]
            - FOR "Commodity Group": Select strictly ONE from this list: CC, CD, CE, CG, CH, CK, CL, CM, CN, CP, CS, CT, CV, CX, CB. 
              (Hint: CC = miniature ceramic, CE = electrolytic, CG = mica, CK = film, CL = ceramic power, CS = suppression). If not found, return "N/A".
            - FOR "Catalogue Group": Select strictly ONE: "Capacitors fixed", "Capacitor Electrolyt", "Capacitor mech. adjustable", or "Capacitor electr. adjustable". If not found, return "N/A".
            - FOR "Manufacturer": Select exactly from this list: binder mpe GmbH, Dalicap Technology Co., Ltd., ebm-papst (Mulfingen) GmbH & Co. KG, Electronicon Kiondensatoren GmbH, Exxelia Group, HIGH ENERGY Corp., Holy Stone Enterprise Co., Ltd., Richard Jahre GmbH, Johanson Precision Corporation, K+B elektromechanische, Knowles Electronics, LLC, Kyocera AVX Components Ltd., MACOM Technology Solutions Holdings, Murata Manufacturing Co., Ltd, Nichicon Corporation, NIPPON CHEMI-CON CORPORATION, OXLEY DEVELOPMENTS, Panasonic Corporation, Presidio Components Inc., PSA Passive System Alliance Group, Rubycon Corporation, Samsung Group, Schlund GmbH, Spectrum Control, Inc., Syfer Technology Ltd., Taiyo Yuden Co., Ltd., TDK Corporation, TE Connectivity Ltd., Tronser GmbH, CTS Corporation, Vishay Intertechnology, Inc., Voltronics Corp., WIMA Spezialvertrieb elektronische, Yageo Corporation. If not found, return "N/A".
            - FOR "Designation": Construct a string following EXACTLY this format: [Capacity] [Tolerance] [Voltage] [Description] [Package Type EIA]. 
              * Example: "100NF 10% 250V X7T 1210". Format the capacity properly (e.g. 100NF, 10UF). 
              * CRITICAL FOR TOLERANCE: For [Tolerance] in the Designation string, you MUST use the numeric percentage (e.g., 5%, 10%) and NEVER the letter code (e.g., J, K, M). Remove any '±' symbol (e.g., strictly use "5%", do not use "±5%" or "J"). Include the % and V symbols.
              * CRITICAL FOR PACKAGE TYPE: For [Package Type EIA] inside this designation string, use ONLY the bare numeric code (e.g., 0603, 1210). Do NOT include the "EIA" prefix or the "*" asterisk.
            - FOR "Capacity [F]": Extract the nominal capacitance value with unit (e.g., 100nF, 10uF).
            - FOR "Tolerance [%]": Extract the numeric tolerance percentage. Remove the '±' symbol (e.g., output "5", not "±5" or "J").
            - FOR "Voltage [V]": Extract the rated voltage.
            - FOR "Package Type" and "Package Type (EIA)": Return the value EXACTLY in this format: EIA[Package EIA Size]*. For example, if the size is 0603, return "EIA0603*". Ensure both keys return this exact same formatted string.
            - FOR "Pitch_Calculation_Logic": 1) Identify the nominal Length (L) in mm. 2) Identify the nominal terminal size / termination band (T) in mm. 3) Output exactly in this format: "Formula: L - T" (e.g., "Formula: 1.60 - 0.35").
            - FOR "Pitch (Footprint) (mm)": Output "N/A" for the "value" field. For the "evidence" field, extract ONLY the exact formula string generated in "Pitch_Calculation_Logic" (e.g., "1.60 - 0.35").
            
            [GENERAL RULES]
            - FOR "Kind of Mounting": Select ONE: "SMT (surface-mounting technology)", "THR, PiP (through-hole technology)", "press-fit", "THW (through-hole technology)", "none".
            - FOR "St. Solder", "Alt. Solder", "Rep. Solder": Use standard options (reflow soldering top/bottom, wave soldering bottom, etc).
            - FOR REFLOW: Extract ONLY the raw nominal numerical value. Discard text/units.
            - FOR "Washability" and "Varnishability": Determine the single letter code based on the Commodity Group and the following criteria. Return ONLY the letter in the "value" field:
              * CB (Feedthrough), CH (Barrier-layer), CM (MP), CN (Networks), CP (Paper), CS (Suppression), CV (Vacuum): Washability="K", Varnishability="K".
              * CD (Variable), CL (Power): Washability="N", Varnishability="N".
              * CC (Ceramic): If SMD type -> Washability="W", Varnishability="L". If other types -> "K", "K".
              * CE (Electrolytic): If without insulating cover/heat-shrinkable sleeve -> "W", "L". If all others -> "K", "K".
              * CG (Mica): If Leaded types -> "W", "L". If SMD types -> "K", "K".
              * CK (Plastic film): If SMD with coating -> "W", "L". If all others -> "K", "K".
              * CT (Trimmer): If with sealing disk -> "K", "K". If all others -> "N", "N".
            - FOR "ESS Suitable": Look at the extracted Operating Temperature range. If the minimum temperature is strictly less than -20°C (e.g., -55, -40) OR the maximum temperature is strictly greater than 75°C (e.g., 85, 125), you MUST return EXACTLY "ESS released". If the entire temperature range fits completely inside -20°C to 75°C, return "not ESS released". Example: A range of -55°C to +125°C exceeds the limits, so you must return "ESS released".
            - FOR "Surface": Identify the contact/termination surface material. Select STRICTLY ONE of the following codes based on the material found: 
              * "SN" (if the material is Tin, Matte Tin, Sn, or Zinn)
              * "AU" (if the material is Gold or Au)
              * "AG-PD" (if the material is Silver-Palladium, AgPd, or Silber Paladium)
              * "AG-SN" (if the material is Silver-Tin, AgSn, or Silber Zinn)
              If the surface material is not explicitly mentioned, return "N/A".
            
            Datasheet Text:
            -----------------
            {pdf_text}
            """
            
            progress_bar.progress(40, text="Analyzing datasheet using AI... This may take a minute.")
            
            max_retries = 3
            retry_delay = 15 
            extracted_data = None
            
            for attempt in range(max_retries):
                try:
                    api_keys = st.secrets["GEMINI_API_KEY"].split(",")
                    selected_key = random.choice(api_keys).strip()
                    genai.configure(api_key=selected_key)
                    model = genai.GenerativeModel('gemini-3.5-flash-lite')
                    
                    response = model.generate_content(
                        full_prompt,
                        generation_config={
                            "temperature": 0.0,
                            "response_mime_type": "application/json"
                        }
                    )
                    extracted_data = json.loads(response.text, strict=False)
                    progress_bar.progress(80, text="AI extraction complete. Parsing data...")
                    break 
                    
                except KeyError:
                    progress_bar.empty()
                    st.error("⚠️ Sila masukkan GEMINI_API_KEY di dalam Streamlit Secrets.")
                    st.stop()
                    
                except Exception as e:
                    if "429" in str(e) or "Quota" in str(e):
                        if attempt < max_retries - 1:
                            progress_bar.progress(40, text=f"API limit reached. Auto-retrying in {retry_delay}s... (Trial {attempt+1}/{max_retries})")
                            time.sleep(retry_delay)
                        else:
                            progress_bar.empty()
                            st.error("Failed after 3 trials. Rilex & wait for a minute, then try again.")
                            st.stop() 
                    else:
                        progress_bar.empty()
                        st.error(f"API Error: {e}")
                        st.stop()
            
            if not extracted_data:
                st.stop()
            
            progress_bar.progress(90, text="Building UI tables and CSV report...")
            
           # --- HELPER UNTUK BERSIHKAN NULL/UNKNOWN KEPADA N/A ---
            def clean_na(val):
                if val is None or str(val).strip().lower() in ["null", "none", "unknown", ""]:
                    return "N/A"
                return str(val)

            # --- ASINGKAN HEADER INFO ---
            designation_dict = extracted_data.pop("Designation", {})
            designation_text = clean_na(designation_dict.get("value", "N/A") if isinstance(designation_dict, dict) else designation_dict).upper()
            
            mfg_dict = extracted_data.pop("Manufacturer", {})
            manufacturer_text = clean_na(mfg_dict.get("value", "N/A") if isinstance(mfg_dict, dict) else mfg_dict)
            
            cat_dict = extracted_data.pop("Catalogue Group", {})
            catalogue_text = clean_na(cat_dict.get("value", "N/A") if isinstance(cat_dict, dict) else cat_dict)
            
            comm_dict = extracted_data.pop("Commodity Group", {})
            commodity_text = clean_na(comm_dict.get("value", "N/A") if isinstance(comm_dict, dict) else comm_dict)

            # --- STANDARDIZE PACKAGE TYPE FORMATTING ---
            if "Package Type" in extracted_data and isinstance(extracted_data["Package Type"], dict):
                pkg_val = str(extracted_data["Package Type"].get("value", "")).strip()
                if pkg_val and pkg_val != "N/A":
                    # Bersihkan perkataan EIA dan tanda * jika ada (untuk elak duplicate)
                    clean_pkg = pkg_val.replace("EIA", "").replace("*", "").strip()
                    std_pkg = f"EIA{clean_pkg}*"
                    
                    extracted_data["Package Type"]["value"] = std_pkg
                    
                    # Salin terus ke Package Type (EIA)
                    if "Package Type (EIA)" not in extracted_data or not isinstance(extracted_data["Package Type (EIA)"], dict):
                        extracted_data["Package Type (EIA)"] = {"value": "N/A", "evidence": "N/A", "page": "N/A"}
                    
                    extracted_data["Package Type (EIA)"]["value"] = std_pkg
                    extracted_data["Package Type (EIA)"]["evidence"] = extracted_data["Package Type"].get("evidence", "N/A")
                    extracted_data["Package Type (EIA)"]["page"] = extracted_data["Package Type"].get("page", "N/A")

            # --- PYTHON MATH OVERRIDE UNTUK PITCH ---
            if "Pitch (Footprint) (mm)" in extracted_data:
                pitch_item = extracted_data["Pitch (Footprint) (mm)"]
                if isinstance(pitch_item, dict):
                    calc_str = str(pitch_item.get("evidence", ""))
                    if "-" in calc_str:
                        try:
                            clean_str = calc_str.replace("Formula:", "").strip(" ()")
                            parts = clean_str.split("-")
                            if len(parts) == 2:
                                pitch_val = float(parts[0].strip()) - float(parts[1].strip())
                                extracted_data["Pitch (Footprint) (mm)"]["value"] = str(round(pitch_val, 4))
                                extracted_data["Pitch (Footprint) (mm)"]["evidence"] = f"{parts[0].strip()} - {parts[1].strip()}"
                        except Exception:
                            pass
            
            extracted_data.pop("Pitch_Calculation_Logic", None)

            st.success("Extraction Complete!")
            progress_bar.progress(100, text="Done!")
            time.sleep(0.5)
            progress_bar.empty()
            
            rekod_mpn = target_mpn.upper() if target_mpn else "General (No MPN)"
            if rekod_mpn not in st.session_state.history:
                st.session_state.history.append(rekod_mpn)
            
            st.info(f"**Standardized Designation:** {designation_text}")
            colA, colB, colC = st.columns(3)
            colA.caption(f"🏢 **Manufacturer:** {manufacturer_text}")
            colB.caption(f"📦 **Commodity Group:** {commodity_text}")
            colC.caption(f"📖 **Catalogue Group:** {catalogue_text}")
            
            # --- DEFINISI KATEGORI ---
            keys_top = ["Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)"]
            keys_library = ["Length [mm]", "Width [mm]", "Height (Max)", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins"]
            keys_processability = ["Kind of Mounting", "Washability", "Varnishability", "St. Solder (Standard Solder)", "Alt. Solder (Alternate Solder)", "Rep. Solder (Repair Solder)", "ESS Suitable", "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)"]
            
            # --- DYNAMIC TECH PARAMETER BASED ON COMMODITY ---
            if commodity_text == "CB":
                keys_techn = ["Function", "Attenuation [dB]", "f Nom. (Typ) [Hz]", "Voltage [V]", "Current [A]", "Inductance [H]", "Tolerance [%]", "Additional Information", "ImpMax [Ohm]", "Insertion Loss (Max) [dB]", "Filter Type", "Package Type", "Length [mm]", "Width [mm]", "Height [mm]", "Capacity [F]", "Resistance [Ohm]", "Impedance@MHz", "ImpMax@MHz [Hz]"]
            elif commodity_text == "CE":
                keys_techn = ["Capacity [F]", "Tolerance [%]", "Ripple Current", "Package Type", "Processing Technology", "Description", "Voltage [V]", "ESR [Ohm]", "Endurance [h/°C]", "Height [mm]"]
            else:
                # Default for CC, CG, CK, CS, CL and others
                keys_techn = ["Capacity [F]", "Tolerance [%]", "Package Type", "Height [mm]", "Voltage [V]", "Description", "Surface", "Additional Information"]

            def build_table(keys_list, data_dict):
                specs, values, units, evidences, pages = [], [], [], [], []
                for key in keys_list:
                    item = data_dict.get(key, {"value": "N/A", "evidence": "N/A", "page": "N/A"})
                    
                    if item is None:
                        val, ev, pg = "N/A", "N/A", "N/A"
                    elif isinstance(item, str):
                        val, ev, pg = item, "N/A", "N/A"
                    else:
                        val = str(item.get("value", "N/A")) if item.get("value") is not None else "N/A"
                        ev = str(item.get("evidence", "N/A")) if item.get("evidence") is not None else "N/A"
                        pg = str(item.get("page", "N/A")) if item.get("page") is not None else "N/A"
                        
                    # Filter output akhir
                    val = clean_na(val)
                    ev = clean_na(ev)
                    pg = clean_na(pg)
                        
                    # Extract Units from Brackets e.g., "Capacity [F]" -> Key: "Capacity", Unit: "F"
                    unit_str = "-"
                    clean_key = key
                    
                    if "[" in key and "]" in key:
                        start_idx = key.find("[")
                        end_idx = key.find("]")
                        unit_str = key[start_idx+1:end_idx]
                        clean_key = key[:start_idx].strip()
                    elif "(°C)" in key: clean_key, unit_str = key.replace(" (°C)", ""), "°C"
                    elif "(mm)" in key: clean_key, unit_str = key.replace(" (mm)", ""), "mm"
                    elif "(%)" in key: clean_key, unit_str = key.replace(" (%)", ""), "%"
                    elif "(s)" in key: clean_key, unit_str = key.replace(" (s)", ""), "s"
                    elif "(cycles)" in key: clean_key, unit_str = key.replace(" (cycles)", ""), "cycles"
                    elif "(Footprint)" in key: clean_key, unit_str = key.replace(" (Footprint)", ""), "mm" # Khas untuk Pitch
                    
                    specs.append(clean_key)
                    values.append(val)
                    units.append(unit_str)
                    evidences.append(ev)
                    pages.append(pg)
                    
                return {"Specification": specs, "Extracted Value": values, "Unit": units, "Page": pages, "Source Evidence": evidences}

            # --- 4 TABS UI ---
            tab1, tab2, tab3, tab4 = st.tabs(["Top", "Library", "Processability", "Techn.Parameter"])
            with tab1: st.table(build_table(keys_top, extracted_data))
            with tab2: st.table(build_table(keys_library, extracted_data))
            with tab3: st.table(build_table(keys_processability, extracted_data))
            with tab4: st.table(build_table(keys_techn, extracted_data))
            
            # --- JANA FAIL EXCEL (CSV) ---
            all_keys = keys_top + keys_library + keys_processability + keys_techn
            all_data = build_table(all_keys, extracted_data)
            
            csv_buffer = io.StringIO()
            csv_buffer.write('\ufeff') 
            
            writer = csv.writer(csv_buffer)
            # Inject Metadata header
            writer.writerow(["Metadata", "Value", "", "", ""])
            writer.writerow(["Standardized Designation", designation_text, "", "", ""])
            writer.writerow(["Manufacturer", manufacturer_text, "", "", ""])
            writer.writerow(["Commodity Group", commodity_text, "", "", ""])
            writer.writerow(["Catalogue Group", catalogue_text, "", "", ""])
            writer.writerow([])
            # Data table header
            writer.writerow(["Specification", "Extracted Value", "Unit", "Page", "Source Evidence"]) 
            
            for i in range(len(all_data["Specification"])):
                writer.writerow([all_data["Specification"][i], all_data["Extracted Value"][i], all_data["Unit"][i], all_data["Page"][i], all_data["Source Evidence"][i]])
            
            st.divider()
            st.download_button(
                label="📥 Download Report (CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"{rekod_mpn}_Capacitor_Report.csv",
                mime="text/csv"
            )
            
        except Exception as e:
            st.error(f"Error Happened!: {e}")
