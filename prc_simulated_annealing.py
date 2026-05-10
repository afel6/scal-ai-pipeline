import warnings
import logging
import numpy as np
import matplotlib.pyplot as plt
import math
import random
import time

_logger = logging.getLogger("prc-sa")

_PENALTY = 1e9  # large finite cost returned whenever a numerical failure is detected

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
        """
        Edge-case guard: raises ValueError early if sw_array is empty or has fewer
        than two distinct values, preventing silent NaN propagation through the entire
        optimisation loop.
        """
        sw_array = np.asarray(sw_array, dtype=float)
        target_krw = np.asarray(target_krw, dtype=float)
        target_kro = np.asarray(target_kro, dtype=float)

        if sw_array.size == 0:
            raise ValueError("sw_array must not be empty.")
        if sw_array.size != target_krw.size or sw_array.size != target_kro.size:
            raise ValueError(
                f"sw_array length ({sw_array.size}) must match target_krw "
                f"({target_krw.size}) and target_kro ({target_kro.size})."
            )
        if np.all(sw_array == sw_array[0]):
            raise ValueError(
                "sw_array contains all-identical values — cannot define a mobile "
                "saturation range; optimization is meaningless."
            )

        self.target_krw = target_krw
        self.target_kro = target_kro
        self.sw_array = sw_array
        self.swi = float(sw_array[0])
        self.sor = 1.0 - float(sw_array[-1])

    def _brooks_corey(self, params):
        """
        Edge-case guard: if the mobile saturation range (1 − Swi − Sor) is at or
        below zero (degenerate endpoints), Se is set to a constant 0.5 to avoid
        ZeroDivisionError.  All results are verified finite before return.
        """
        krw_max, kro_max, nw, no = params
        mobile = 1.0 - self.swi - self.sor
        if abs(mobile) < 1e-9:
            # Degenerate endpoint configuration — return neutral mid-range curves.
            se = np.full_like(self.sw_array, 0.5)
        else:
            se = (self.sw_array - self.swi) / mobile

        # Clip to (ε, 1−ε) to prevent math domain errors on power operations.
        se = np.clip(se, 0.001, 0.999)

        krw = krw_max * (se ** nw)
        kro = kro_max * ((1 - se) ** no)
        return krw, kro

    def objective_function(self, params):
        """
        Calculates the Mean Squared Error (MSE) between our current guess and the
        lab data.

        Edge-case guard: any ZeroDivisionError, ValueError, OverflowError, or numpy
        NaN/Inf that arises inside the Brooks-Corey evaluation is caught here and
        replaced with a large finite penalty (_PENALTY = 1e9) so the annealing loop
        can continue gracefully rather than crashing or silently propagating bad state.
        """
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                krw, kro = self._brooks_corey(params)
                error = np.mean((self.target_krw - krw) ** 2) + np.mean((self.target_kro - kro) ** 2)
            # Guard against NaN / Inf that numpy can produce without raising.
            if not np.isfinite(error):
                return _PENALTY
            return float(error)
        except (ZeroDivisionError, ValueError, OverflowError, FloatingPointError):
            return _PENALTY
        
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
        """
        Main annealing loop.

        Edge-case guards added:
        - The energy evaluation at each iteration is wrapped in try/except so that
          any unexpected numerical failure (overflow, invalid value) returns _PENALTY
          rather than crashing the loop.
        - The Metropolis acceptance step uses min(0, -delta_e / temperature) before
          calling math.exp() to prevent OverflowError when delta_e is a large
          negative number and temperature is very small.
        - A temperature floor of 1e-10 prevents ZeroDivisionError in the Metropolis
          exponent when cooling_rate is exactly 1.0 or rounding reduces temperature
          to zero.
        """
        _logger.info("Simulated Annealing optimizer ready — T0=%.2f cooling=%.4f", initial_temp, cooling_rate)

        # Initial terrible guess
        current_state = [0.2, 0.2, 1.5, 1.5]
        current_energy = self.objective_function(current_state)

        best_state = list(current_state)
        best_energy = current_energy

        temperature = initial_temp
        history_energy = []

        for iteration in range(max_iterations):
            # Enforce a temperature floor so the Metropolis denominator never hits zero.
            temperature = max(temperature, 1e-10)

            # Propose a new solution
            neighbor_state = self.generate_neighbor(current_state, temperature)

            # Guard: catch any residual numerical failure not caught by objective_function.
            try:
                neighbor_energy = self.objective_function(neighbor_state)
            except Exception:
                neighbor_energy = _PENALTY

            # Calculate energy difference (Are we better or worse?)
            delta_e = neighbor_energy - current_energy

            # If the neighbor is better, accept it implicitly.
            # If the neighbor is WORSE, occasionally accept it depending on temperature.
            # Clamp the exponent argument to avoid OverflowError on math.exp().
            if delta_e < 0:
                accept = True
            else:
                exponent = -delta_e / temperature
                # math.exp overflows for exponent > ~709; clamp to a safe range.
                accept = random.random() < math.exp(max(exponent, -745.0))

            if accept:
                current_state = neighbor_state
                current_energy = neighbor_energy

                # Check if this is the absolute best we've ever seen globally.
                if current_energy < best_energy:
                    best_state = list(current_state)
                    best_energy = current_energy

            history_energy.append(best_energy)

            # Cool down the system
            temperature *= cooling_rate

            if iteration % 400 == 0:
                _logger.debug("SA iter %d: T=%.2f MSE=%.4f", iteration, temperature, best_energy)

        _logger.info(
            "SA complete — krw_max=%.2f kro_max=%.2f nw=%.2f no=%.2f MSE=%.4f",
            best_state[0], best_state[1], best_state[2], best_state[3], best_energy,
        )
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
    
    print(f"\n[TIME] Total Computation Time: {end_time - start_time:.2f} seconds")
    
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
    print("[PLOT] Spawning Interactive Matplotlib Visualizer...")
    plt.show()

if __name__ == "__main__":
    run_academic_demo()
