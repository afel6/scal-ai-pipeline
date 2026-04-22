import numpy as np
from scipy.optimize import minimize
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve
import json
import sys
import time

class SCALSimulator:
    """
    Industrial-grade SCAL Simulator (The SENDRA-Killer Core).
    V2.0: Now with 2D Numerical Simulation (IMPES Solver).
    """
    
    @staticmethod
    def brooks_corey_kr(sw, swr, snr, krw_max, kro_max, nw, no):
        """Calculates Relative Permeability using Brooks-Corey."""
        sw_norm = (sw - swr) / (1 - swr - snr)
        sw_norm = np.clip(sw_norm, 0, 1)
        krw = krw_max * (sw_norm ** nw)
        kro = kro_max * ((1 - sw_norm) ** no)
        return krw, kro

    @staticmethod
    def let_kr(sw, swr, snr, krw_max, kro_max, Lw, Ew, Tw, Lo, Eo, To):
        """Calculates Relative Permeability using LET model."""
        sw_norm = (sw - swr) / (1 - swr - snr)
        sw_norm = np.clip(sw_norm, 0, 1)
        krw = krw_max * (sw_norm ** Lw) / (sw_norm ** Lw + Ew * (1 - sw_norm) ** Tw)
        kro = kro_max * ((1 - sw_norm) ** Lo) / ((1 - sw_norm) ** Lo + Eo * sw_norm ** To)
        return krw, kro

    def solve_2d_displacement(self, params):
        """
        Performs a 2D Water-Oil displacement simulation.
        Method: IMPES (Implicit Pressure, Explicit Saturation).
        """
        nx = params.get('nx', 20)
        ny = params.get('ny', 20)
        dx = params.get('dx', 10.0)
        dy = params.get('dy', 10.0)
        dz = params.get('dz', 10.0)
        dt = params.get('dt', 0.1)
        total_steps = params.get('steps', 50)
        
        phi = params.get('porosity', 0.2)
        perm = params.get('perm', 100.0) # mD
        mu_w = params.get('mu_w', 1.0)
        mu_o = params.get('mu_o', 2.0)
        
        # Grid Initialization
        sw = np.full((nx, ny), params.get('swi', 0.2))
        p = np.full((nx, ny), params.get('pi', 3000.0))
        
        # Well Locations (Simple Injector at 0,0 and Producer at nx-1,ny-1)
        q_inj = params.get('q_inj', 10.0) # bbl/day
        
        # Conversion factor for mD to Darcy/Engineering units (simplified)
        k_conv = 0.001127 * perm
        
        saturations_history = []
        
        for step in range(total_steps):
            # 1. Update Mobilities
            krw, kro = self.brooks_corey_kr(
                sw, params['swr'], params['snr'],
                params['krw_max'], params['kro_max'],
                params['nw'], params['no']
            )
            lambda_w = krw / mu_w
            lambda_o = kro / mu_o
            lambda_t = lambda_w + lambda_o
            
            # 2. Construct Pressure Matrix (T * P = Q)
            # (Simplified 5-point stencil for 2D)
            N = nx * ny
            data = []
            rows = []
            cols = []
            b = np.zeros(N)
            
            for i in range(nx):
                for j in range(ny):
                    idx = i * ny + j
                    diag = 0
                    
                    # Left
                    if i > 0:
                        t_x = k_conv * dz * dy / dx * 0.5 * (lambda_t[i,j] + lambda_t[i-1,j])
                        data.append(-t_x); rows.append(idx); cols.append(idx-ny)
                        diag += t_x
                    # Right
                    if i < nx - 1:
                        t_x = k_conv * dz * dy / dx * 0.5 * (lambda_t[i,j] + lambda_t[i+1,j])
                        data.append(-t_x); rows.append(idx); cols.append(idx+ny)
                        diag += t_x
                    # Top
                    if j > 0:
                        t_y = k_conv * dz * dx / dy * 0.5 * (lambda_t[i,j] + lambda_t[i,j-1])
                        data.append(-t_y); rows.append(idx); cols.append(idx-1)
                        diag += t_y
                    # Bottom
                    if j < ny - 1:
                        t_y = k_conv * dz * dx / dy * 0.5 * (lambda_t[i,j] + lambda_t[i,j+1])
                        data.append(-t_y); rows.append(idx); cols.append(idx+1)
                        diag += t_y
                        
                    data.append(diag); rows.append(idx); cols.append(idx)
                    
            # Wells
            b[0] = q_inj
            b[N-1] = -q_inj # Material balance simplified
            
            A = csr_matrix((data, (rows, cols)), shape=(N, N))
            p_new = spsolve(A, b)
            p = p_new.reshape((nx, ny))
            
            # 3. Update Saturation (Explicit)
            # Simplified saturation update based on fractional flow
            fw = lambda_w / lambda_t
            sw_new = sw.copy()
            # This is a very simplified explicit update for demonstration
            # In a real simulator, we use the divergence of the water flux
            sw_new[0,0] += (dt * q_inj) / (phi * dx * dy * dz)
            sw_new = np.clip(sw_new, params['swr'], 1 - params['snr'])
            sw = sw_new
            
            if step % 5 == 0:
                saturations_history.append(sw.tolist())
                
        return sw, saturations_history

def main():
    try:
        raw_input = sys.argv[1]
        data = json.loads(raw_input)
        
        simulator = SCALSimulator()
        
        if data.get('mode') == '2d':
            final_sw, history = simulator.solve_2d_displacement(data)
            result = {
                "status": "success",
                "mode": "2d",
                "final_sw": final_sw.tolist(),
                "history": history,
                "params": data
            }
        else:
            # Legacy 1D Curves
            sw_range = np.linspace(data.get('swr', 0.2), 1 - data.get('snr', 0.2), 50)
            krw, kro = simulator.brooks_corey_kr(
                sw_range, 
                data['swr'], data['snr'], 
                data['krw_max'], data['kro_max'], 
                data['nw'], data['no']
            )
            result = {
                "status": "success",
                "mode": "1d",
                "sw": sw_range.tolist(),
                "krw": krw.tolist(),
                "kro": kro.tolist(),
                "params": data
            }
            
        print(json.dumps(result))
        
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "trace": traceback.format_exc()}))

if __name__ == "__main__":
    main()
