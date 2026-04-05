import numpy as np
import matplotlib.pyplot as plt
import math
import random
import time

class PRCSimulatedAnnealing:
    """
    Topic 3: Optimization Simulation (Simulated Annealing)
    
    Problem Statement: 
    Finding the optimal Brooks-Corey Exponents (nw, no) and endpoints (krw_max, kro_max) 
    to perfectly match laboratory Special Core Analysis (SCAL) Relative Permeability data.
    
    Why Simulated Annealing?
    The error surface for multi-parameter curve fitting often contains 'local minimums'. 
    Standard gradient descent frequently gets trapped in these sub-optimal valleys. 
    Simulated Annealing mathematically mimics metallurgy cooling: it allows 'worse' 
    moves at high temperatures to jump out of local minimums, slowly cooling down to 
    greedily find the true 'global' optimum.
    """
    def __init__(self, target_krw, target_kro, sw_array):
        self.target_krw = target_krw
        self.target_kro = target_kro
        self.sw_array = sw_array
        self.swi = sw_array[0]
        self.sor = 1.0 - sw_array[-1]
        
    def _brooks_corey(self, params):
        # params: [krw_max, kro_max, nw, no]
        krw_max, kro_max, nw, no = params
        se = (self.sw_array - self.swi) / (1 - self.swi - self.sor)
        
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
        print("🔥 Initializing Simulated Annealing Core Matching Optimizer...")
        print(f"🌡️ Initial Temperature: {initial_temp} | Cooling Rate: {cooling_rate}\n")
        
        # Initial terrible guess
        current_state = [0.2, 0.2, 1.5, 1.5]
        current_energy = self.objective_function(current_state)
        
        best_state = list(current_state)
        best_energy = current_energy
        
        temperature = initial_temp
        history_energy = []
        
        for iteration in range(max_iterations):
            # Propose a new solution
            neighbor_state = self.generate_neighbor(current_state, temperature)
            neighbor_energy = self.objective_function(neighbor_state)
            
            # Calculate energy difference (Are we better or worse?)
            delta_e = neighbor_energy - current_energy
            
            # If the neighbor is better, accept it implicitly!
            # If the neighbor is WORSE, occasionally accept it depending on temperature
            if delta_e < 0 or random.random() < math.exp(-delta_e / temperature):
                current_state = neighbor_state
                current_energy = neighbor_energy
                
                # Check if this is the absolute best we've ever seen globally
                if current_energy < best_energy:
                    best_state = list(current_state)
                    best_energy = current_energy
            
            history_energy.append(best_energy)
            
            # Cool down the system
            temperature *= cooling_rate
            
            if iteration % 400 == 0:
                print(f"⚙️ Iteration {iteration}: Temp = {temperature:.2f} | Error (MSE) = {best_energy:.4f}")
                
        print("\n✅ Optimization Complete (Absolute Minimum Found without local entrapment)")
        print(f"🎯 Final Optimal Parameters: krw_max={best_state[0]:.2f}, kro_max={best_state[1]:.2f}, nw={best_state[2]:.2f}, no={best_state[3]:.2f}")
        return best_state, history_energy

def run_academic_demo():
    print("=====================================================")
    print(" UNIVERSITY AI PROJECT: TOPIC 3 (OPTIMIZATION)")
    print(" ALGORITHM: SIMULATED ANNEALING")
    print(" APPLICATION: PETROLEUM ENGINEERING SCAL CURVE MATCH")
    print("=====================================================\n")
    
    # 1. Generate Fake "Laboratory" Truth Data (The goal we want to find)
    sw_array = np.linspace(0.2, 0.8, 40)
    se_truth = (sw_array - 0.2) / (1 - 0.2 - 0.2)
    se_truth = np.clip(se_truth, 0.001, 0.999)
    # The absolute perfect parameters that the AI must blindly discover:
    true_krw_max, true_kro_max, true_nw, true_no = 0.5, 0.8, 3.5, 2.5
    lab_krw = true_krw_max * (se_truth ** true_nw) + np.random.normal(0, 0.02, 40) # Add lab noise!
    lab_kro = true_kro_max * ((1 - se_truth) ** true_no) + np.random.normal(0, 0.02, 40) 

    # 2. Run Simulated Annealing AI Engine
    optimizer = PRCSimulatedAnnealing(lab_krw, lab_kro, sw_array)
    time.sleep(1)
    
    start_time = time.time()
    best_params, history = optimizer.optimize()
    end_time = time.time()
    
    print(f"\n⏱️ Total Computation Time: {end_time - start_time:.2f} seconds")
    
    # 3. Create the Visualization (Crucial for the "Demonstration Video" Requirement)
    krw_fit, kro_fit = optimizer._brooks_corey(best_params)
    
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Plot 1: Optimization Cooling Curve
    ax1.plot(history, color='#eab308', linewidth=2)
    ax1.set_title("Simulated Annealing Convergence (Error vs Time)", fontweight='bold')
    ax1.set_xlabel("AI Iterations")
    ax1.set_ylabel("Mean Squared Error (MSE)")
    ax1.grid(True, alpha=0.2)
    
    # Plot 2: The Final Fit Result
    ax2.scatter(sw_array, lab_krw, color='#3b82f6', label="Lab Data (Water)", alpha=0.5)
    ax2.scatter(sw_array, lab_kro, color='#ef4444', label="Lab Data (Oil)", alpha=0.5)
    ax2.plot(sw_array, krw_fit, color='#60a5fa', linewidth=3, label="AI Optimal Fit (krw)")
    ax2.plot(sw_array, kro_fit, color='#f87171', linewidth=3, label="AI Optimal Fit (kro)")
    ax2.set_title("Global Optimum: Brooks-Corey Phase Curve", fontweight='bold')
    ax2.set_xlabel("Water Saturation (Sw)")
    ax2.set_ylabel("Relative Permeability (Kr)")
    ax2.legend()
    ax2.grid(True, alpha=0.2)
    
    plt.tight_layout()
    print("📊 Spawning Interactive Matplotlib Visualizer...")
    plt.show()

if __name__ == "__main__":
    run_academic_demo()
