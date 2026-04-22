import sys
import json
import math
import random
import numpy as np

class PRCSimulatedAnnealing:
    def __init__(self, target_krw, target_kro, sw_array):
        self.target_krw = np.array(target_krw)
        self.target_kro = np.array(target_kro)
        self.sw_array = np.array(sw_array)
        self.swi = self.sw_array[0]
        self.sor = 1.0 - self.sw_array[-1]
        
    def _brooks_corey(self, params):
        # params: [krw_max, kro_max, nw, no]
        krw_max, kro_max, nw, no = params
        se = (self.sw_array - self.swi) / (1 - self.swi - self.sor + 1e-9)
        
        # Clip precision slightly to prevent math domain errors 
        se = np.clip(se, 0.001, 0.999)
        
        krw = krw_max * (se ** nw)
        kro = kro_max * ((1 - se) ** no)
        return krw, kro
        
    def objective_function(self, params):
        """Calculates the Mean Squared Error (MSE) between our current guess and the lab data."""
        krw, kro = self._brooks_corey(params)
        error = np.mean((self.target_krw - krw)**2) + np.mean((self.target_kro - kro)**2)
        return error
        
    def generate_neighbor(self, current_params, temperature):
        """Creates a slightly mutated new guess based on the current heat of the system."""
        # Parameter Bounds: krw_max (0.1 to 1.0), kro_max(0.1 to 1.0), nw (1 to 6), no (1 to 6)
        bounds = [(0.1, 1.0), (0.1, 1.0), (1.0, 6.0), (1.0, 6.0)]
        
        new_params = []
        for i in range(4):
            # The higher the temperature, the more chaotic the jump
            mutation_step = random.uniform(-1, 1) * temperature * (bounds[i][1] - bounds[i][0]) * 0.1
            mutated_val = current_params[i] + mutation_step
            # Clamp to physical constraints
            mutated_val = max(bounds[i][0], min(bounds[i][1], mutated_val))
            new_params.append(mutated_val)
            
        return new_params

    def optimize(self, initial_temp=100.0, cooling_rate=0.99, max_iterations=2000):
        # Initial terrible guess
        current_state = [0.2, 0.2, 1.5, 1.5]
        current_energy = self.objective_function(current_state)
        
        best_state = list(current_state)
        best_energy = current_energy
        
        temperature = initial_temp
        
        for iteration in range(max_iterations):
            neighbor_state = self.generate_neighbor(current_state, temperature)
            neighbor_energy = self.objective_function(neighbor_state)
            
            delta_e = neighbor_energy - current_energy
            
            if delta_e < 0 or random.random() < math.exp(-delta_e / temperature):
                current_state = neighbor_state
                current_energy = neighbor_energy
                
                if current_energy < best_energy:
                    best_state = list(current_state)
                    best_energy = current_energy
            
            temperature *= cooling_rate
            
        return best_state, best_energy

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            input_data = json.loads(sys.argv[1])
        else:
            input_data = json.loads(sys.stdin.read())
            
        sw = input_data.get("sw", [])
        krw = input_data.get("krw", [])
        kro = input_data.get("kro", [])
        
        if not sw or not krw or not kro:
            print(json.dumps({"error": "Missing required arrays: sw, krw, and/or kro"}))
            sys.exit(1)
            
        if len(sw) != len(krw) or len(sw) != len(kro):
            print(json.dumps({"error": "Arrays sw, krw, and kro must be of equal length"}))
            sys.exit(1)
            
        optimizer = PRCSimulatedAnnealing(krw, kro, sw)
        best_params, final_mse = optimizer.optimize()
        
        result = {
            "success": True,
            "message": "History matching optimization completed via Simulated Annealing.",
            "final_mse": float(final_mse),
            "optimal_parameters": {
                "krw_max": float(best_params[0]),
                "kro_max": float(best_params[1]),
                "nw": float(best_params[2]),
                "no": float(best_params[3])
            }
        }
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({"error": f"Internal execution error: {str(e)}"}))
        sys.exit(1)
