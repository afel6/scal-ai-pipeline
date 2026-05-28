import os
import json
from typing import List, Dict, Any
import matplotlib
# Use Non-interactive Agg backend to avoid GUI window opening or thread blocks
matplotlib.use('Agg')
from matplotlib.figure import Figure

def generate_plots(json_data: List[Dict[str, Any]], output_dir: str = None, streamlit_code: str = None) -> str:
    """
    Generates standard laboratory curves using thread-safe Matplotlib OO API and saves them in the output directory.
    
    1. Porosity (%) vs. Overburden Pressure (psi)
    2. Air Permeability (mD) vs. Overburden Pressure (psi)
    
    Also exports the validated JSON to outputs/validated_scal_data.json.
    If streamlit_code is provided, programmatically saves the dynamic Streamlit dashboard to outputs/app_dashboard.py.
    """
    if not output_dir:
        # Default to /outputs in the workspace root
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "outputs")
        
    os.makedirs(output_dir, exist_ok=True)

    if streamlit_code:
        dashboard_path = os.path.join(output_dir, "app_dashboard.py")
        with open(dashboard_path, "w", encoding="utf-8") as f:
            f.write(streamlit_code)
        print(f"[Visualizer] Programmatically saved Streamlit dashboard: {dashboard_path}")
    
    # 1. Parse and extract data points, filtering out None values
    pressures = []
    porosities = []
    perms = []
    
    for row in json_data:
        pressure = row.get("Pressure_psi")
        porosity = row.get("Porosity_percent")
        perm = row.get("Air_Permeability_md")
        
        # We need pressure to plot, and at least one of porosity or permeability
        if pressure is not None:
            pressures.append(pressure)
            porosities.append(porosity)
            perms.append(perm)
            
    # Zip and filter so we only plot non-None coordinates for each curve
    porosity_plot_data = [(p, phi) for p, phi in zip(pressures, porosities) if p is not None and phi is not None]
    perm_plot_data = [(p, k) for p, k in zip(pressures, perms) if p is not None and k is not None]
    
    # Sort by pressure just in case
    porosity_plot_data.sort(key=lambda x: x[0])
    perm_plot_data.sort(key=lambda x: x[0])
    
    # --- Plot 1: Porosity (%) vs. Overburden Pressure (psi) ---
    if porosity_plot_data:
        p_coords = [x[0] for x in porosity_plot_data]
        phi_coords = [x[1] for x in porosity_plot_data]
        
        fig = Figure(figsize=(8, 5))
        ax = fig.subplots()
        # Sleek professional styling: dark blue with circle markers
        ax.plot(p_coords, phi_coords, marker='o', linestyle='-', color='#0F4C81', linewidth=2, markersize=6, label='Porosity')
        ax.set_title('Porosity vs. Overburden Pressure', fontsize=12, fontweight='bold', pad=15)
        ax.set_xlabel('Overburden Pressure (psi)', fontsize=10, fontweight='bold')
        ax.set_ylabel('Porosity (%)', fontsize=10, fontweight='bold')
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend(loc='best')
        
        porosity_path = os.path.join(output_dir, "porosity_vs_pressure.png")
        fig.savefig(porosity_path, dpi=300, bbox_inches='tight')
        fig.clf()
        print(f"[Visualizer] Generated: {porosity_path}")
    else:
        print("[Visualizer] Warning: No valid Porosity vs Pressure data points found to plot.")
        
    # --- Plot 2: Air Permeability (mD) vs. Overburden Pressure (psi) ---
    if perm_plot_data:
        p_coords = [x[0] for x in perm_plot_data]
        k_coords = [x[1] for x in perm_plot_data]
        
        fig = Figure(figsize=(8, 5))
        ax = fig.subplots()
        # Sleek professional styling: emerald green with square markers
        ax.plot(p_coords, k_coords, marker='s', linestyle='-', color='#10B981', linewidth=2, markersize=6, label='Air Permeability')
        ax.set_title('Air Permeability vs. Overburden Pressure', fontsize=12, fontweight='bold', pad=15)
        ax.set_xlabel('Overburden Pressure (psi)', fontsize=10, fontweight='bold')
        ax.set_ylabel('Air Permeability (mD)', fontsize=10, fontweight='bold')
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend(loc='best')
        
        perm_path = os.path.join(output_dir, "permeability_vs_pressure.png")
        fig.savefig(perm_path, dpi=300, bbox_inches='tight')
        fig.clf()
        print(f"[Visualizer] Generated: {perm_path}")
    else:
        print("[Visualizer] Warning: No valid Air Permeability vs Pressure data points found to plot.")
        
    # --- Export pristine validated JSON ---
    json_path = os.path.join(output_dir, "validated_scal_data.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2)
    print(f"[Visualizer] Exported validated data JSON: {json_path}")
    
    return output_dir

if __name__ == "__main__":
    # Test layout
    test_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": 45.2
        },
        {
            "Pressure_psi": 1200.0,
            "Porosity_percent": 18.2,
            "Air_Permeability_md": 44.8
        },
        {
            "Pressure_psi": 2000.0,
            "Porosity_percent": 17.8,
            "Air_Permeability_md": 42.1
        }
    ]
    generate_plots(test_data)
