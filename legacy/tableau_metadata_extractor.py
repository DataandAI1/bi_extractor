#!/usr/bin/env python3
import os
import zipfile
import xml.etree.ElementTree as ET
import csv
import json
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# --- Core Extraction Functions ---

def extract_twb_tree(path):
    """Extract the TWB XML tree from a TWB or TWBX file"""
    if path.lower().endswith('.twbx'):
        with zipfile.ZipFile(path, 'r') as zf:
            twb = next(n for n in zf.namelist() if n.lower().endswith('.twb'))
            with zf.open(twb) as f:
                return ET.parse(f), os.path.basename(path)
    return ET.parse(path), os.path.basename(path)


def clean_calculation_formula(raw_formula, calc_map):
    """Clean formula by replacing calculation IDs with their names/captions"""
    if not raw_formula:
        return raw_formula, "No Formula"
    
    cleaned = raw_formula
    status = "Success"
    replacements_made = 0
    
    try:
        # Pattern 1: [Calculation_1234567890123] format
        calc_pattern = r'\[Calculation_(\d+)\]'
        
        def replace_calc_id(match):
            nonlocal replacements_made
            calc_id = match.group(1)
            if calc_id in calc_map:
                replacements_made += 1
                return f"[{calc_map[calc_id]}]"
            return match.group(0)
        
        cleaned = re.sub(calc_pattern, replace_calc_id, cleaned)
        
        # Pattern 2: @{id} style references
        at_pattern = r'@\{(\d+)\}'
        
        def replace_at_id(match):
            nonlocal replacements_made
            calc_id = match.group(1)
            if calc_id in calc_map:
                replacements_made += 1
                return f"[{calc_map[calc_id]}]"
            return match.group(0)
        
        cleaned = re.sub(at_pattern, replace_at_id, cleaned)
        
        # Pattern 3: Direct numeric references [1234567890123]
        direct_id_pattern = r'\[(\d{10,})\]'  # Long numeric IDs
        
        def replace_direct_id(match):
            nonlocal replacements_made
            calc_id = match.group(1)
            if calc_id in calc_map:
                replacements_made += 1
                return f"[{calc_map[calc_id]}]"
            return match.group(0)
        
        cleaned = re.sub(direct_id_pattern, replace_direct_id, cleaned)
        
        # Pattern 4: Check for any remaining unresolved calculation references
        if replacements_made == 0 and re.search(r'\[Calculation_\d+\]|\[\d{10,}\]|@\{\d+\}', raw_formula):
            status = "Unresolved References"
        
        # If we made replacements but there are still unresolved ones
        if replacements_made > 0 and re.search(r'\[Calculation_\d+\]|\[\d{10,}\]|@\{\d+\}', cleaned):
            status = "Partially Resolved"
    
    except Exception as e:
        status = f"Error: {str(e)}"
        cleaned = raw_formula
    
    return cleaned, status


def extract_all_data(root, filename):
    """Extract all data from a Tableau workbook"""
    data = {
        'fields': [],
        'calculations': {},
        'field_worksheet_usage': [],
        'connections': {}
    }
    
    # First pass: Build calculation ID to caption/alias mapping
    calc_id_to_caption = {}
    
    # Extract from columns with calculation elements
    for col in root.findall('.//column'):
        calc_elem = col.find('.//calculation')
        if calc_elem is not None:
            calc_id = calc_elem.get('id', '')
            if calc_id:
                # Use caption if available, otherwise use name
                caption = col.get('caption', col.get('name', ''))
                if caption:
                    calc_id_to_caption[calc_id] = caption
    
    # Extract from standalone calculations
    for calc in root.findall('.//calculation'):
        calc_id = calc.get('id', '')
        if calc_id:
            # Use caption if available, otherwise use name
            caption = calc.get('caption', calc.get('name', ''))
            if caption:
                calc_id_to_caption[calc_id] = caption
    
    # Store the mapping
    data['calculations'] = calc_id_to_caption
    
    # Extract datasource information
    for ds in root.findall('.//datasource'):
        ds_name = ds.get('name', '')
        ds_caption = ds.get('caption', ds_name)
        
        # Extract connection info
        conn = ds.find('.//connection')
        if conn is not None:
            conn_class = conn.get('class', '')
            conn_name = conn.get('server', conn.get('filename', conn.get('database', '')))
            data['connections'][ds_name] = {
                'name': conn_name,
                'alias': ds_caption,
                'class': conn_class
            }
        
        # Extract columns/fields
        for col in ds.findall('.//column'):
            field_name = col.get('name', '')
            field_caption = col.get('caption', field_name)
            
            # Check if this is a calculated field
            calc_elem = col.find('.//calculation')
            formula = ''
            field_type = 'Dimension'  # Default
            
            if calc_elem is not None:
                formula = calc_elem.get('formula', '')
                field_type = 'Calculated Field'
                calc_class = calc_elem.get('class', '')
                if 'tableau' in calc_class:
                    field_type = 'Table Calculation'
                
                # Also add this calculation ID mapping if it has one
                calc_id = calc_elem.get('id', '')
                if calc_id and field_caption:
                    data['calculations'][calc_id] = field_caption
            
            # Determine field type based on role and aggregation
            elif col.get('role') == 'measure':
                field_type = 'Measure'
                if col.get('aggregation'):
                    field_type = 'Aggregated Measure'
            
            data['fields'].append({
                'name': field_name,
                'caption': field_caption,
                'datatype': col.get('datatype', ''),
                'role': col.get('role', ''),
                'datasource': ds_name,
                'formula': formula,
                'field_type': field_type
            })
    
    # Extract standalone calculations that might not be in columns
    for calc in root.findall('.//calculation'):
        calc_name = calc.get('name', '')
        calc_caption = calc.get('caption', calc_name)
        formula = calc.get('formula', '')
        
        # Add to fields if not already there
        if calc_name and not any(f['name'] == calc_name for f in data['fields']):
            data['fields'].append({
                'name': calc_name,
                'caption': calc_caption,
                'datatype': calc.get('datatype', ''),
                'role': calc.get('role', ''),
                'datasource': '',
                'formula': formula,
                'field_type': 'Calculated Field'
            })
    
    # Extract field usage in worksheets
    for ws in root.findall('.//worksheet'):
        ws_name = ws.get('name', '')
        
        # Get datasource dependencies
        for dep in ws.findall('.//datasource-dependencies'):
            ds_name = dep.get('datasource', '')
            
            for col in dep.findall('.//column'):
                field_name = col.get('name', '')
                if field_name:
                    data['field_worksheet_usage'].append({
                        'field': field_name,
                        'worksheet': ws_name,
                        'datasource': ds_name
                    })
        
        # Also check for fields in encodings
        for enc_col in ws.findall('.//encoding//column'):
            field_ref = enc_col.text or enc_col.get('column', '')
            if field_ref:
                # Remove brackets if present
                if field_ref.startswith('[') and field_ref.endswith(']'):
                    field_ref = field_ref[1:-1]
                
                data['field_worksheet_usage'].append({
                    'field': field_ref,
                    'worksheet': ws_name,
                    'datasource': ''
                })
    
    # Remove duplicates from field_worksheet_usage
    seen = set()
    unique_usage = []
    for usage in data['field_worksheet_usage']:
        key = (usage['field'], usage['worksheet'])
        if key not in seen:
            seen.add(key)
            unique_usage.append(usage)
    data['field_worksheet_usage'] = unique_usage
    
    return data


def build_final_output(all_workbook_data):
    """Build the final output matching the sample format"""
    final_rows = []
    column_id = 1
    
    for filename, data in all_workbook_data.items():
        # Create calculation map for this workbook
        calc_map = data['calculations']
        
        # Get all fields
        fields_by_name = {f['name']: f for f in data['fields']}
        
        # Get worksheet usage
        usage_by_field = {}
        for usage in data['field_worksheet_usage']:
            field = usage['field']
            if field not in usage_by_field:
                usage_by_field[field] = []
            usage_by_field[field].append(usage['worksheet'])
        
        # Process each field
        for field in data['fields']:
            field_name = field['name']
            worksheets = usage_by_field.get(field_name, [''])
            
            # Get connection info
            conn_info = data['connections'].get(field['datasource'], {})
            conn_name = conn_info.get('name', '')
            conn_alias = conn_info.get('alias', field['datasource'])
            
            # Clean formula if it exists
            original_formula = field.get('formula', '')
            cleaned_formula = ''
            clean_status = 'No Calculation'
            
            if original_formula:
                cleaned_formula, clean_status = clean_calculation_formula(original_formula, calc_map)
            
            # Create one row per worksheet (or one row if not used in any worksheet)
            if not worksheets:
                worksheets = ['']
            
            for worksheet in worksheets:
                # Determine if field is used in this worksheet
                field_used = 'Yes' if worksheet else 'No'
                
                final_rows.append({
                    'Column ID': column_id,
                    'Column Name': field_name,
                    'Column Alias': field.get('caption', ''),
                    'Field Type': field.get('field_type', ''),
                    'Connection Name': conn_name,
                    'Connection Alias': conn_alias,
                    'datatype': field.get('datatype', ''),
                    'role': field.get('role', ''),
                    'Calculation Formula': cleaned_formula,
                    'Original Calculation': original_formula,
                    'Calc Clean Status': clean_status,
                    'Field Used in Worksheets': field_used,
                    'Worksheet Name': worksheet,
                    'File Name': filename
                })
                column_id += 1
    
    return final_rows


def process_all_files(input_dir):
    """Process all Tableau files in the input directory"""
    all_workbook_data = {}
    
    for root_dir, _, files in os.walk(input_dir):
        for f in files:
            if f.lower().endswith(('.twb', '.twbx')):
                try:
                    filepath = os.path.join(root_dir, f)
                    tree, filename = extract_twb_tree(filepath)
                    root = tree.getroot()
                    
                    print(f"Processing {filename}...")
                    data = extract_all_data(root, filename)
                    all_workbook_data[filename] = data
                    
                except Exception as e:
                    print(f"Error processing {f}: {str(e)}")
                    continue
    
    return all_workbook_data


def write_final_csv(output_dir, final_rows):
    """Write the final CSV file"""
    if not final_rows:
        print("No data to write")
        return
    
    output_path = os.path.join(output_dir, 'tableau_metadata.csv')
    
    # Define column order to match sample
    fieldnames = [
        'Column ID',
        'Column Name', 
        'Column Alias',
        'Field Type',
        'Connection Name',
        'Connection Alias',
        'datatype',
        'role',
        'Calculation Formula',
        'Original Calculation',
        'Calc Clean Status',
        'Field Used in Worksheets',
        'Worksheet Name',
        'File Name'
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final_rows)
    
    print(f"Wrote {len(final_rows)} rows to {output_path}")


# --- GUI Application ---

class TableauMetadataExtractor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Tableau Metadata Extractor')
        self.geometry('600x400')
        
        # Create main frame
        main_frame = tk.Frame(self, padx=10, pady=10)
        main_frame.pack(fill='both', expand=True)
        
        # Input folder selection
        tk.Label(main_frame, text='Input Folder:', font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        
        input_frame = tk.Frame(main_frame)
        input_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=5)
        
        self.input_path = tk.StringVar()
        self.input_entry = tk.Entry(input_frame, textvariable=self.input_path, width=50)
        self.input_entry.pack(side='left', fill='x', expand=True)
        
        tk.Button(input_frame, text='Browse...', command=self.browse_input).pack(side='right', padx=(5, 0))
        
        # Output folder selection
        tk.Label(main_frame, text='Output Folder:', font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky='w', pady=5)
        
        output_frame = tk.Frame(main_frame)
        output_frame.grid(row=3, column=0, columnspan=2, sticky='ew', pady=5)
        
        self.output_path = tk.StringVar()
        self.output_entry = tk.Entry(output_frame, textvariable=self.output_path, width=50)
        self.output_entry.pack(side='left', fill='x', expand=True)
        
        tk.Button(output_frame, text='Browse...', command=self.browse_output).pack(side='right', padx=(5, 0))
        
        # Process button
        self.process_btn = tk.Button(main_frame, text='Extract Metadata', command=self.process_files,
                                    bg='#4CAF50', fg='white', font=('Arial', 12, 'bold'),
                                    padx=20, pady=10)
        self.process_btn.grid(row=4, column=0, columnspan=2, pady=20)
        
        # Progress/Log area
        tk.Label(main_frame, text='Progress Log:', font=('Arial', 10, 'bold')).grid(row=5, column=0, sticky='w', pady=5)
        
        log_frame = tk.Frame(main_frame)
        log_frame.grid(row=6, column=0, columnspan=2, sticky='nsew', pady=5)
        
        # Configure grid weights
        main_frame.grid_rowconfigure(6, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        
        # Create scrollbar
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side='right', fill='y')
        
        # Create text widget for log
        self.log_text = tk.Text(log_frame, height=10, wrap='word', yscrollcommand=scrollbar.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.log_text.yview)
    
    def browse_input(self):
        folder = filedialog.askdirectory(title='Select Input Folder')
        if folder:
            self.input_path.set(folder)
    
    def browse_output(self):
        folder = filedialog.askdirectory(title='Select Output Folder')
        if folder:
            self.output_path.set(folder)
    
    def log(self, message):
        self.log_text.insert('end', f"{message}\n")
        self.log_text.see('end')
        self.update()
    
    def process_files(self):
        input_dir = self.input_path.get()
        output_dir = self.output_path.get()
        
        # Validate inputs
        if not input_dir or not os.path.isdir(input_dir):
            messagebox.showerror('Error', 'Please select a valid input folder')
            return
        
        if not output_dir or not os.path.isdir(output_dir):
            messagebox.showerror('Error', 'Please select a valid output folder')
            return
        
        # Clear log
        self.log_text.delete(1.0, 'end')
        self.log('Starting metadata extraction...')
        
        try:
            # Disable button during processing
            self.process_btn.config(state='disabled')
            
            # Redirect print to log
            import sys
            from io import StringIO
            
            class LogRedirect:
                def __init__(self, log_func):
                    self.log_func = log_func
                
                def write(self, text):
                    if text.strip():
                        self.log_func(text.strip())
                
                def flush(self):
                    pass
            
            old_stdout = sys.stdout
            sys.stdout = LogRedirect(self.log)
            
            # Process files
            self.log('Scanning for Tableau files...')
            all_data = process_all_files(input_dir)
            
            if not all_data:
                self.log('No Tableau files found!')
                messagebox.showwarning('Warning', 'No Tableau files found in the input folder')
                return
            
            self.log(f'Found {len(all_data)} Tableau file(s)')
            self.log('Building final output...')
            
            final_rows = build_final_output(all_data)
            
            self.log('Writing output CSV...')
            write_final_csv(output_dir, final_rows)
            
            # Restore stdout
            sys.stdout = old_stdout
            
            self.log('Extraction completed successfully!')
            messagebox.showinfo('Success', f'Metadata extraction completed!\nOutput saved to: {os.path.join(output_dir, "tableau_metadata.csv")}')
            
        except Exception as e:
            sys.stdout = old_stdout
            self.log(f'Error: {str(e)}')
            messagebox.showerror('Error', f'An error occurred: {str(e)}')
        
        finally:
            # Re-enable button
            self.process_btn.config(state='normal')


if __name__ == '__main__':
    app = TableauMetadataExtractor()
    app.mainloop()
