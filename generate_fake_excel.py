import pandas as pd
import numpy as np

# Generate physical water saturation points
sw = np.linspace(0.15, 0.85, 20)

# True Corey Parameters
krw_max, kro_max, nw, no = 0.6, 0.8, 2.5, 2.0
swi, sor = 0.15, 0.15

# Calculate base Kr curves
se = (sw - swi) / (1 - swi - sor)
se = np.clip(se, 0.001, 0.999)
krw_clean = krw_max * (se ** nw)
kro_clean = kro_max * ((1 - se) ** no)

# Add lab noise
krw_noisy = np.clip(krw_clean + np.random.normal(0, 0.02, len(sw)), 0, 1)
kro_noisy = np.clip(kro_clean + np.random.normal(0, 0.02, len(sw)), 0, 1)

df = pd.DataFrame({
    'Sw': sw,
    'Krw': krw_noisy,
    'Kro': kro_noisy
})

# Save to the root so the browser subagent can find it easily
df.to_excel('fake_scal_data.xlsx', index=False)
print("Created fake_scal_data.xlsx successfully!")
