import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

# Load the original sheet
df = pd.read_excel('your_file.xlsx', sheet_name=0)  # Change sheet name/index if needed

# Column name for owner - change this to your actual column name
OWNER_COLUMN = 'Owner Name'  # <-- Change this

wb = load_workbook('your_file.xlsx')
ws_new = wb.create_sheet('Grouped by Owner')

headers = list(df.columns)
current_row = 1

for owner, group in df.groupby(OWNER_COLUMN, sort=True):
    # Write owner name row
    ws_new.cell(row=current_row, column=1, value=owner).font = Font(bold=True, size=13)
    current_row += 1

    # Write "GBT Records" label
    ws_new.cell(row=current_row, column=1, value='GBT Records').font = Font(bold=True, italic=True)
    current_row += 1

    # Write column headers
    for col_idx, header in enumerate(headers, start=1):
        cell = ws_new.cell(row=current_row, column=col_idx, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', start_color='4472C4')
        cell.alignment = Alignment(horizontal='center')
    current_row += 1

    # Write data rows for this owner
    for _, row in group.iterrows():
        for col_idx, value in enumerate(row, start=1):
            ws_new.cell(row=current_row, column=col_idx, value=value)
        current_row += 1

    # 2 blank rows between owners
    current_row += 2

# Auto-fit column widths
for col in ws_new.columns:
    max_len = max((len(str(cell.value)) for cell in col if cell.value), default=10)
    ws_new.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

wb.save('your_file.xlsx')
print("Done! Check the 'Grouped by Owner' sheet.")
