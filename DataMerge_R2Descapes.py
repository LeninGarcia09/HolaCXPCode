import pandas as pd
from tkinter import Tk
from tkinter.filedialog import askopenfilename

# Prompt user to select files
Tk().withdraw()
print("Select the older Excel file:")
file1 = askopenfilename(filetypes=[("Excel files", "*.xlsx")])

print("Select the more recent Excel file:")
file2 = askopenfilename(filetypes=[("Excel files", "*.xlsx")])

# Ask for the name of the date column
date_column = input("Enter the name of the date column to sort by (case-sensitive): ")

# Load both Excel files
excel1 = pd.ExcelFile(file1)
excel2 = pd.ExcelFile(file2)

# Get sheet names
sheet_names_1 = set(excel1.sheet_names)
sheet_names_2 = set(excel2.sheet_names)

# Union of sheet names
union_sheets = sheet_names_1.union(sheet_names_2)

# Dictionary to hold combined data
combined_sheets = {}

# Combine and sort data from each sheet
for sheet in union_sheets:
    df1 = pd.read_excel(file1, sheet_name=sheet) if sheet in sheet_names_1 else None
    df2 = pd.read_excel(file2, sheet_name=sheet) if sheet in sheet_names_2 else None

    if df1 is not None and df2 is not None:
        combined_df = pd.concat([df1, df2], ignore_index=True)
    elif df1 is not None:
        combined_df = df1.copy()
    elif df2 is not None:
        combined_df = df2.copy()
    else:
        combined_df = pd.DataFrame()

    # Sort by
