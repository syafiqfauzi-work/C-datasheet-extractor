import streamlit as st
import google.generativeai as genai
import PyPDF2
import json
import time   
import random 
import csv 
import io
import os
from datetime import datetime

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="RG Datasheet Analyzer", page_icon="📄")
st.title("📄 RG Datasheet Analyzer")
st.write("Upload a datasheet (PDF) and the AI will extract the key specifications.")

# Baca metadata tarikh fail app.py ini terakhir disunting
file_path = __file__
modified_timestamp = os.path.getmtime(file_path)
last_update_date = datetime.fromtimestamp(modified_timestamp).strftime("%d/%m/%Y")

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

# --- UI DUAL UPLOAD ---
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
                    try:
                        spec_reader.decrypt("")
                    except Exception:
                        pass
                spec_text = "".join([page.extract_text() for page in spec_reader.pages if page.extract_text()])
                pdf_text += f"\n\n=== CRITICAL PRIORITY: SPECIFIC SPEC SHEET ===\n{spec_text}\n\n=== GENERAL DATASHEET ===\n"
            
            # --- BACA DATASHEET SEPERTI BIASA ---
            if uploaded_file is not None:
                reader = PyPDF2.PdfReader(uploaded_file)
                
                # --- PENAPIS KESELAMATAN (SECURITY BYPASS) ---
                if reader.is_encrypted:
                    try:
                        reader.decrypt("") # Buka kunci AES dengan kata laluan kosong
                    except Exception:
                        st.error("General PDF file is encrypted with Password. Please find un-encrypted PDF.")
                        st.stop()
                # ---------------------------------------------
                
                total_pages = len(reader.pages)
                
                # Fasa 1: Membaca PDF (0% - 30%)
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
            Review the provided datasheet text and accurately extract the requested information. 
            
            Extract these exact keys:
            "Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", 
            "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)", 
            "Length (mm)", "Width (mm)", "Height_Calculation_Logic", "Height (Max)", "Height (mm)", 
            "Package Type", "Package Type (EIA)", "Pitch_Calculation_Logic", "Pitch (Footprint) (mm)", "Number of Pins", "Resistance_Calculation_Logic", 
            "Resistance (Ohm)", "Tolerance (%)", "Row_Data_Extraction", "Voltage (V)", "Function", 
            "Power_Extraction_Logic", "Power Consumption (W)", "TCR_Calculation_Logic", "Temperature Coefficient",
            "Kind of Mounting", "Washability", "Varnishability", "St. Solder (Standard Solder)", 
            "Alt. Solder (Alternate Solder)", "Rep. Solder (Repair Solder)", "ESS Suitable", 
            "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)",
            "Manufacturer", "Designation", "Additional Information", "Quantity"

            Important Instructions:
            - Return strictly a valid JSON object with the keys above.
            - CRITICAL JSON RULE 1: Do NOT use unescaped double quotes (") inside any of your text explanations or values. Use single quotes (') instead.
            - CRITICAL JSON RULE 2: Do NOT include raw newline characters (\n), carriage returns (\r), or tabs (\t) inside any JSON string values. Replace them with standard spaces.
            - FOR ALL OTHER KEYS: Return a nested JSON object with three fields: "value" (the string value, or "N/A"), "evidence" (a short exact quote from the text), and "page" (the exact Page number where it was found, e.g., "1", or "N/A").
            
            [PROCESSABILITY RULES]
            - FOR "Kind of Mounting": Select ONLY ONE: "SMT (surface-mounting technology)", "THR, PiP (through-hole technology)", "press-fit", "THW (through-hole technology)", "ceramic substrate technology (Chip microwave)", "none", or "fine press-fit".
              * CRITICAL LOGIC: If the datasheet mentions traditional leaded components or soldering via "wave or dipping", select "THW (through-hole technology)". If it explicitly mentions "Through-Hole Reflow", "THR", or "Pin-in-Paste (PiP)", select "THR, PiP (through-hole technology)". If it is a standard surface mount chip/SMD, select "SMT (surface-mounting technology)".
            - FOR "St. Solder (Standard Solder)": Select ONLY ONE: "reflow soldering top / bottom", "reflow soldering top - only", "wave soldering bottom", "manually soldering / bonding", or "no soldering".
            - FOR "Alt. Solder (Alternate Solder)": Select ONLY ONE: "selective hot air soldering", "wave soldering bottom", "selective wave soldering", "manually soldering", or "no soldering".
            - FOR "Rep. Solder (Repair Solder)": Select ONLY ONE: "selective hot air soldering", "manually soldering", or "no soldering".
            - FOR "ESS Suitable": Evaluate the extracted Storage Temperatures. If the Storage Temperature goes OUTSIDE the standard standard range (e.g., Min is colder than -20°C OR Max is hotter than 75°C), select "ESS released". If the temperatures fall strictly WITHIN -20°C to 75°C (like +5 to +35 °C), select "not ESS released". If there is no information available for the Storage Temperature, strictly return "N/A".
            - FOR "Washability" and "Varnishability": Select "Yes" or "No" if explicitly stated in the datasheet. If there is no information available regarding washability or varnishability, strictly return "N/A".
            - FOR REFLOW ("Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)"): Extract ONLY the raw nominal numerical value. Discard any text, units (e.g., seconds, s, °C, cycles), and tolerances (e.g., for "10 ± 1 seconds immersion time", return "10"; for "260 °C ± 5 °C", return "260").
            
            [GENERAL RULES]
            - MASTER RULE FOR SPEC SHEETS: If the text contains a "CRITICAL PRIORITY: SPECIFIC SPEC SHEET" section, you MUST extract all available values directly from that section first. You are ALLOWED to skip complex table extraction logic. HOWEVER, for calculated fields like Height (Max), Pitch, or Voltage, you MUST still write your exact mathematical step-by-step calculation in the "evidence" field, followed by the tag "(From Spec Sheet)". Example: "Pitch = Length (5.08) - Terminal (1.47) (From Spec Sheet)" or "Height = 0.64 + 0.25 (From Spec Sheet)".
            - FOR "Resistance_Calculation_Logic": If a target MPN is provided, determine the resistance code. 1) If the code contains an 'R' (e.g., R300, R3000, 1R50), extract it. If it starts with 'R', prepend a '0' (e.g., R300 -> 0R300). Then remove trailing zeros at the end (e.g., 0R300 -> 0R3, 1R50 -> 1R5). 2) If it is a standard numeric code (e.g., 1828), let XYZ=182, M=8. If M='7' output "0RXYZ"; If M='8' output "XRYZ"; If M='9' output "XYRZ"; If M='0' output "XYZR"; If M='1' output "XKYZ"; If M='2' output "XYKZ"; If M='3' output "XYZK"; If M='4' output "XMYZ"; If M='5' output "XYMZ"; If M='6' output "XYZM".
            - FOR "Resistance (Ohm)": Extract ONLY the final string generated from the XYZ rule in "Resistance_Calculation_Logic". ABSOLUTELY NO DECIMALS.
            - FOR "Row_Data_Extraction": PDF tables are flattened. Find the target Part No. (e.g., ERJP06). The values immediately following it are typically: [Size] [Power] [Ambient Temp] [Terminal Temp] [Limiting Voltage] [Overload Voltage]. (e.g., "ERJP06 (0805) 0.50 70 115 400 600"). Isolate and write down this exact sequence for your specific MPN to prevent grabbing data from the wrong row.
            - FOR "Voltage (V)": Look STRICTLY at the isolated sequence in "Row_Data_Extraction". Extract the "Limiting element voltage" (which is typically the 4th numeric value after the package size). Example: If the sequence is "0.50 70 115 400", the voltage is 400. Do NOT grab voltages from other part numbers.
            - FOR "TCR_Calculation_Logic": Look at the isolated data for your specific Part No. 1) State the exact resistance in Ohms. 2) Find the T.C.R. sub-ranges for this part. 3) Evaluate the resistance mathematically. Example: 1000 Ohms is greater than 33 Ohms, so it matches the condition "33Ω ≤ R : ±100" (NOT R < 33Ω). 4) State the correct T.C.R.
            - FOR "Temperature Coefficient": Look STRICTLY at the mathematical range you just determined in "TCR_Calculation_Logic". Extract ONLY the specific T.C.R. value assigned to that exact range. Extract the numerical value TOGETHER WITH its exact unit (e.g., "200 ppm/°C"). Discard "±".
            - FOR DIMENSIONS (Length, Width, Height (mm)): If a value includes a tolerance (e.g., 0.60 ± 0.03), extract ONLY the nominal base value (e.g., 0.60) and discard the tolerance completely.
            - FOR THE "Function" KEY: Select ONLY ONE: "Thin Film", "Thick Film", "Metal Foil", "Wire-wound", or "Carbon Film".
            - FOR "Height_Calculation_Logic": 1) Extract the raw height dimension string. 2) If it contains dual units like "inches (mm)", you MUST isolate ONLY the millimeter portion completely inside the parentheses (e.g., from "0.025 ± 0.010 (0.635 ± 0.254)", isolate "0.635 ± 0.254"). 3) Identify the nominal mm value (X) and the positive mm tolerance (Y). 4) Output EXACTLY in this format: "X + Y" (e.g., "0.635 + 0.254"). DO NOT compute.
            - FOR "Height (Max)": Output "N/A" (This will be calculated externally).
            - FOR "Height (mm)": Extract ONLY the nominal mm value identified in "Height_Calculation_Logic", discarding any tolerance. Do NOT extract values labeled "T" (Thickness/Terminal) if "H" (Height) is available.
            - FOR "Package Type": Return the value EXACTLY in this format: EIA[Package EIA Size]*. For example, if the size is 0201, return "EIA0201*". Do NOT extract shipping or delivery packaging methods (e.g., Tape and Reel, Paper Taping Reel, Bulk, Tube).
            - FOR "Power_Extraction_Logic": CRITICAL PRIORITY CHECK: If a "CRITICAL PRIORITY: SPECIFIC SPEC SHEET" section exists and explicitly lists a "Power" value (e.g., "1 W (70C)"), you MUST stop searching, extract this exact value, and write "Directly extracted from Priority Spec Sheet" as your logic. DO NOT calculate or compare anything else. If NO spec sheet is provided, THEN proceed to standard logic: 1) Identify target package size. 2) List all Wattage (W) values in the General Datasheet for this size. 3) Select the LOWER numeric value as Standard mode and write the comparison.
            - FOR "Power Consumption (W)": Extract ONLY the final FIRST numeric value determined in "Power_Extraction_Logic". Convert fractions to decimals if needed.
            - FOR VOLTAGE: If the datasheet lists multiple operation modes (e.g., "Standard" vs "Extended"), strictly extract the values for the "Standard" operation mode. Do not extract the Extended or maximum rating if a Standard mode is available.
              * Note 1: If Power is provided as a fraction (e.g., 1/20, 1/4, 1/8), you MUST calculate and return it strictly as a DECIMAL (e.g., 0.05, 0.25, 0.125) for both the "Power Consumption (W)" key and the "Designation" string.
              * Note 2: If the datasheet specifies a formula like "(P x R)1/2" instead of a direct number, calculate it mathematically using your final Power (W) and Resistance (Ohm) values. Round the final calculated value to exactly 4 decimal places (e.g., "0.5477") for the "value" field. In the "evidence" field, write your step-by-step calculation (e.g., "Formula: (P x R)^1/2 -> sqrt(1.0W x 0.3Ohm)").
           - FOR "Pitch_Calculation_Logic": YOU MUST OUTPUT A MATRIX. 1) State nominal Length (L) in mm. 2) List ALL Terminal Widths (T) and their exact Resistance Ranges line-by-line (e.g., "Range 1: 0.001 to 0.0069, T = 1.47 | Range 2: 0.007 to 0.5, T = 0.508"). 3) State the target MPN resistance. 4) State exactly which range it falls into by comparing decimals. 5) Output the final formula AT THE VERY END in exactly this format: "Formula: L - T" (e.g., "Formula: 5.08 - 0.508").
            - FOR "Pitch (Footprint) (mm)": Output "N/A" for the "value" field. For the "evidence" field, extract ONLY the exact formula string generated at the very end of "Pitch_Calculation_Logic" (e.g., "5.08 - 0.508"). Discard the matrix text.
            - FOR THE "Designation" KEY: Construct a string following EXACTLY this format: 
              [Resistance] [Tolerance] [Temperature coefficient] [Power] [RAW Package EIA] [Additional Info]
              * Note 1: For [Resistance], strictly use the R/K/M formatted value (e.g., use "5R11", do NOT use "5.11"). CRITICAL FOR JUMPERS: If the component is a Jumper (or has 0 Ohm resistance), you MUST explicitly set [Resistance] to "0R" at the very beginning of the designation. Do NOT leave it blank. For jumpers, you should replace the [Power] section with the maximal applicable current (e.g., "40A").
              * Note 2: For [RAW Package EIA], use ONLY the bare numeric code (e.g., 0201, 0402). Do NOT include the "EIA" prefix or the "*" asterisk in this designation string.
              * Note 3: For [Additional Info] in Designation, scan the datasheet and append ONLY these exact tags if found (separate with '/'): HF, PP, HP, HV, AS, FT, SM, AIN, AU, AG, CU. (CRITICAL: Do NOT include "AQ" or Automotive Grade in this designation string). If no tags apply, leave empty. Evaluate these specific mappings:
                - "HF": High Frequency (CRITICAL: Do NOT append this tag if the letters "HF" in the datasheet refer to "Halogen Free" or are associated with RoHS/environmental compliance).
                - "PP": High Pulse, Pulse Proof, or Anti Surge
                - "HP": High Power (power higher than standard)
                - "HV": High Voltage
                - "AS": Anti Sulfurated or Anti-Sulfur
                - "FT": Flexiterm, Flexible Termination, or Soft Termination
                - "SM": Special Mounting (Flange, Chassis, Stacked)
                - "AIN": Aluminium Nitride material
                - "AU": Gold (Au) contact surface
                - "AG": Silver (Ag) contact surface
                - "CU": Copper (Cu) contact surface
              * Note 4: For [Temperature coefficient], use ONLY the numeric value followed by "PPM". You MUST drop the "/K" or "/°C" completely. Example: use "50PPM", NEVER "50PPM/K" or "50PPM/°C".
              * Example output: 5R11 1% 200PPM 0.1W 0603 PP/AS
            - FOR "Manufacturer": Identify the manufacturer of the component from the datasheet. You MUST select strictly from this exact list: "Analog Devices, Inc.", "Barry Industries Inc.", "Bourns Inc.", "Caddock Electronics, Inc", "Diconex", "EMC TECHNIK & CONSULTING GmbH", "Fenghua (H.K.) Electronics Ltd.", "IMS - International Manufacturing S", "Kyocera AVX Components Ltd.", "Mini-Circuits, Inc.", "Panasonic Corporation", "RES-NET Microwave, Inc.", "Smiths Interconnect", "Susumu Co., LTD", "TDK Corporation", "TTM Technologies Inc.", "Vishay Intertechnology, Inc.", or "Yageo Corporation". If the exact manufacturer is not in this list, return "Unknown".
            - FOR "Additional Information": Scan the datasheet for special qualifications. If the component is AEC-Q200 qualified or explicitly stated as Automotive Grade, you MUST extract and output "AQ". You may also list other special features here if found. If nothing is found, return "N/A".
            - FOR "Quantity": Determine the number of isolated resistor elements or circuits within the component package. For a standard single chip resistor, strictly return "1" for the value, and for the "evidence" field, you MUST output this exact fixed statement: "Standard single chip resistor". For resistor arrays or networks, return the exact number of elements (e.g., "2", "4") and quote the relevant array feature as evidence.
            
            Datasheet Text:
            -----------------
            {pdf_text}
            """
            
            # Fasa 2: Menghantar ke AI (30% - 80%)
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
            
            # Fasa 3: Menyusun UI & CSV (80% - 100%)
            progress_bar.progress(90, text="Building UI tables and CSV report...")
            
            # Asingkan Designation
            designation_text = extracted_data.pop("Designation", "N/A")
            if isinstance(designation_text, dict): 
                designation_text = designation_text.get("value", "N/A")
            designation_text = str(designation_text).upper()
            
            # --- ASINGKAN MANUFACTURER ---
            manufacturer_text = extracted_data.pop("Manufacturer", "Unknown")
            if isinstance(manufacturer_text, dict): 
                manufacturer_text = manufacturer_text.get("value", "Unknown")
            # -----------------------------
            
            # --- STANDARDIZE RESISTANCE (e.g., R300 -> 0R3) ---
            if "Resistance (Ohm)" in extracted_data and isinstance(extracted_data["Resistance (Ohm)"], dict):
                res_val = str(extracted_data["Resistance (Ohm)"].get("value", "")).upper()
                if res_val and res_val != "N/A":
                    original_res = res_val
                    
                    # Tambah '0' jika bermula dengan 'R' (contoh: R300 -> 0R300)
                    if res_val.startswith("R"):
                        res_val = "0" + res_val
                        
                    # Buang sifar di belakang (trailing zeros) jika ada huruf R, K, atau M
                    if any(char in res_val for char in ["R", "K", "M"]):
                        res_val = res_val.rstrip("0")
                    
                    # Kemaskini jadual UI
                    extracted_data["Resistance (Ohm)"]["value"] = res_val
                    
                    # Kemaskini Designation supaya sepadan (hanya ubah perkataan rintangan pertama)
                    if designation_text.startswith(original_res):
                        designation_text = designation_text.replace(original_res, res_val, 1)
            # -------------------------------------------------
            
            # PENAPIS KETAT: Buang unit /K atau /°C pada PPM
            designation_text = designation_text.replace("PPM/K", "PPM").replace("PPM/°C", "PPM").replace("PPM/C", "PPM")

            # --- PENAPIS KETAT: Buang tag HF dan AQ dari Designation ---
            if "HF" in designation_text and "high frequency" not in pdf_text.lower() and "microwave" not in pdf_text.lower():
                designation_text = designation_text.replace("HF", "")
            
            # Paksa buang AQ dari Designation (kerana ia kini berada di Additional Information)
            designation_text = designation_text.replace("AQ", "").replace("  ", " ").replace("//", "/").strip(" /")
            
            # --- TALLY PACKAGE TYPE ---
            # Paksa 'Package Type (EIA)' menyalin bulat-bulat data dari 'Package Type'
            if "Package Type" in extracted_data and isinstance(extracted_data["Package Type"], dict):
                extracted_data["Package Type (EIA)"] = extracted_data["Package Type"].copy()

            # --- PYTHON MATH OVERRIDE UNTUK PITCH ---
            if "Pitch (Footprint) (mm)" in extracted_data:
                pitch_item = extracted_data["Pitch (Footprint) (mm)"]
                if isinstance(pitch_item, dict):
                    calc_str = str(pitch_item.get("evidence", ""))
                    if "-" in calc_str:
                        try:
                            # Bersihkan tag spec sheet dan label formula
                            clean_str = calc_str.replace("(From Spec Sheet)", "").replace("Priority Spec Sheet", "")
                            clean_str = clean_str.replace("Formula:", "").strip(" ()")
                            parts = clean_str.split("-")
                            if len(parts) == 2:
                                pitch_val = float(parts[0].strip()) - float(parts[1].strip())
                                extracted_data["Pitch (Footprint) (mm)"]["value"] = str(round(pitch_val, 4))
                                extracted_data["Pitch (Footprint) (mm)"]["evidence"] = clean_str
                        except Exception:
                            pass
            
            # --- PYTHON MATH OVERRIDE UNTUK HEIGHT ---
            if "Height_Calculation_Logic" in extracted_data:
                calc_item = extracted_data["Height_Calculation_Logic"]
                if isinstance(calc_item, dict):
                    calc_str = str(calc_item.get("value", ""))
                    if "+" in calc_str:
                        try:
                            parts = calc_str.split("+")
                            h_max = float(parts[0].strip()) + float(parts[1].strip())
                            
                            if "Height (Max)" not in extracted_data or not isinstance(extracted_data["Height (Max)"], dict):
                                extracted_data["Height (Max)"] = {"value": "N/A", "evidence": "N/A", "page": "N/A"}
                            
                            extracted_data["Height (Max)"]["value"] = str(round(h_max, 4))
                            extracted_data["Height (Max)"]["evidence"] = calc_str
                        except Exception:
                            pass
            
            # Buang kertas conteng AI dari paparan jadual
            extracted_data.pop("TCR_Calculation_Logic", None)
            extracted_data.pop("Resistance_Calculation_Logic", None)
            extracted_data.pop("Row_Data_Extraction", None)
            extracted_data.pop("Power_Extraction_Logic", None)
            extracted_data.pop("Pitch_Calculation_Logic", None)
            extracted_data.pop("Height_Calculation_Logic", None)
            
            st.success("Extraction Complete!")
            progress_bar.progress(100, text="Done!")
            time.sleep(0.5)
            progress_bar.empty() # Hilangkan bar selepas selesai
            
            # Simpan History
            rekod_mpn = target_mpn.upper() if target_mpn else "General (No MPN)"
            if rekod_mpn not in st.session_state.history:
                st.session_state.history.append(rekod_mpn)
            
            st.info(f"**Standardized Designation:** {designation_text}")
            st.caption(f"🏢 **Manufacturer:** {manufacturer_text}")
            
            # --- DEFINISI KATEGORI ---
            keys_top = ["Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)"]
            keys_library = ["Length (mm)", "Width (mm)", "Height (Max)", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins"]
            keys_processability = ["Kind of Mounting", "Washability", "Varnishability", "St. Solder (Standard Solder)", "Alt. Solder (Alternate Solder)", "Rep. Solder (Repair Solder)", "ESS Suitable", "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)"]
            keys_techn = ["Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Package Type", "Quantity", "Function", "Power Consumption (W)", "Temperature Coefficient", "Height (mm)", "Additional Information"]

            def build_table(keys_list, data_dict):
                specs, values, units, evidences, pages = [], [], [], [], []
                for key in keys_list:
                    item = data_dict.get(key, {"value": "N/A", "evidence": "N/A", "page": "N/A"})
                    if isinstance(item, str):
                        val, ev, pg = item, "N/A", "N/A"
                    else:
                        val = item.get("value", "N/A")
                        ev = item.get("evidence", "N/A")
                        pg = item.get("page", "N/A")
                        
                    # Asingkan Unit
                    unit_str = "-"
                    if key == "Temperature Coefficient" and val != "N/A":
                        if "ppm/°C" in val:
                            val, unit_str = val.replace("ppm/°C", "").strip(), "ppm/°C"
                        elif "ppm/K" in val:
                            val, unit_str = val.replace("ppm/K", "").strip(), "ppm/K"
                        elif "ppm/C" in val: 
                            val, unit_str = val.replace("ppm/C", "").strip(), "ppm/°C"
                            
                    elif "(°C)" in key: key, unit_str = key.replace(" (°C)", ""), "°C"
                    elif "(mm)" in key: key, unit_str = key.replace(" (mm)", ""), "mm"
                    elif "(Ohm)" in key: key, unit_str = key.replace(" (Ohm)", ""), "Ohm"
                    elif "(%)" in key: key, unit_str = key.replace(" (%)", ""), "%"
                    elif "(V)" in key: key, unit_str = key.replace(" (V)", ""), "V"
                    elif "(W)" in key: key, unit_str = key.replace(" (W)", ""), "W"
                    elif "(ppm/K)" in key: key, unit_str = key.replace(" (ppm/K)", ""), "ppm/K"
                    elif "(s)" in key: key, unit_str = key.replace(" (s)", ""), "s"
                    elif "(cycles)" in key: key, unit_str = key.replace(" (cycles)", ""), "cycles"
                    
                    specs.append(key)
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
            writer.writerow(["Specification", "Extracted Value", "Unit", "Page", "Source Evidence"]) 
            
            for i in range(len(all_data["Specification"])):
                writer.writerow([all_data["Specification"][i], all_data["Extracted Value"][i], all_data["Unit"][i], all_data["Page"][i], all_data["Source Evidence"][i]])
            
            st.divider()
            st.download_button(
                label="📥 Download Report (CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"{rekod_mpn}_Report.csv",
                mime="text/csv"
            )
            
        except Exception as e:
            st.error(f"Error Happened!: {e}")
