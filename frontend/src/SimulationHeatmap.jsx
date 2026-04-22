import React, { useState, useEffect } from 'react';
import { Play, Pause, FastForward, Activity } from 'lucide-react';

const SimulationHeatmap = ({ content }) => {
  const [data, setData] = useState(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    try {
      const parsed = JSON.parse(content);
      if (parsed.status === 'success' && parsed.mode === '2d') {
        setData(parsed);
      } else {
        setError("Invalid simulation data format.");
      }
    } catch (err) {
      setError("Failed to parse simulation output.");
    }
  }, [content]);

  useEffect(() => {
    let interval;
    if (isPlaying && data && currentStep < data.history.length - 1) {
      interval = setInterval(() => {
        setCurrentStep(prev => {
          if (prev >= data.history.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 500); // 500ms per frame
    } else if (currentStep >= (data?.history.length || 1) - 1) {
      setIsPlaying(false);
    }
    return () => clearInterval(interval);
  }, [isPlaying, currentStep, data]);

  if (error) {
    return (
      <div className="p-4 bg-red-950/30 border border-red-900/50 rounded-xl text-red-400 text-sm font-mono">
        {error}
      </div>
    );
  }

  if (!data) return null;

  const { history, params } = data;
  const nx = params.nx || 20;
  const ny = params.ny || 20;
  
  // Current grid state
  const grid = history[currentStep] || [];

  // Map saturation (0 to 1) to a color
  // High water sat = blue, high oil sat (low water) = black/brown
  const getColor = (val) => {
    // Interpolate from deep oil color to bright water color
    const v = Math.min(Math.max(val, 0), 1);
    // Oil: rgb(30, 20, 10), Water: rgb(20, 120, 255)
    const r = Math.round(30 + v * (20 - 30));
    const g = Math.round(20 + v * (120 - 20));
    const b = Math.round(10 + v * (255 - 10));
    return `rgb(${r}, ${g}, ${b})`;
  };

  return (
    <div className="my-6 bg-[#0c0c10] border border-yellow-900/30 rounded-2xl overflow-hidden shadow-2xl">
      {/* Header */}
      <div className="bg-gradient-to-r from-yellow-950/40 to-slate-900/40 px-4 py-3 flex items-center justify-between border-b border-yellow-900/30">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-yellow-500" />
          <h3 className="text-yellow-400 font-bold tracking-widest text-[11px] uppercase">
            2D Numerical Saturation Front
          </h3>
        </div>
        <div className="text-slate-400 text-[10px] font-mono">
          GRID: {nx}x{ny} | MODEL: {params.model?.toUpperCase()}
        </div>
      </div>

      {/* Main Heatmap Area */}
      <div className="p-6 flex flex-col items-center bg-[#050505]">
        <div 
          className="grid gap-[1px] bg-slate-800 p-[1px] border border-slate-700/50 rounded shadow-lg"
          style={{ 
            gridTemplateColumns: `repeat(${ny}, minmax(0, 1fr))`,
            width: '100%',
            maxWidth: '400px',
            aspectRatio: `${ny} / ${nx}`
          }}
        >
          {grid.map((row, i) => 
            row.map((cell, j) => (
              <div 
                key={`${i}-${j}`} 
                className="w-full h-full transition-colors duration-300"
                style={{ backgroundColor: getColor(cell) }}
                title={`Sw: ${(cell * 100).toFixed(1)}%`}
              />
            ))
          )}
        </div>
      </div>

      {/* Controls */}
      <div className="bg-[#111116] p-4 border-t border-slate-800/60">
        <div className="flex items-center gap-4 mb-3">
          <button 
            onClick={() => {
              if (currentStep >= history.length - 1) setCurrentStep(0);
              setIsPlaying(!isPlaying);
            }}
            className="w-10 h-10 rounded-full bg-yellow-600 hover:bg-yellow-500 text-black flex items-center justify-center transition-transform active:scale-95 shadow-lg shrink-0"
          >
            {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
          </button>
          
          <div className="flex-1 flex flex-col gap-1">
            <div className="flex justify-between text-[10px] font-mono text-slate-500">
              <span>Time: 0</span>
              <span className="text-yellow-500 font-bold">Step {currentStep}</span>
              <span>End</span>
            </div>
            <input 
              type="range" 
              min="0" 
              max={history.length - 1} 
              value={currentStep}
              onChange={(e) => {
                setCurrentStep(parseInt(e.target.value));
                setIsPlaying(false);
              }}
              className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-yellow-500"
            />
          </div>
          
          <button 
            onClick={() => setCurrentStep(history.length - 1)}
            className="w-8 h-8 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-400 flex items-center justify-center transition-colors shrink-0"
            title="Skip to end"
          >
            <FastForward className="w-3.5 h-3.5" />
          </button>
        </div>
        
        {/* Legend */}
        <div className="flex items-center justify-between text-[10px] font-mono uppercase text-slate-500 px-2 mt-4 border-t border-slate-800/40 pt-3">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-sm border border-slate-700" style={{ backgroundColor: getColor(params.swr || 0.2) }} />
            <span>Residual Water</span>
          </div>
          <div className="flex-1 h-1.5 mx-4 rounded-full" style={{ background: `linear-gradient(to right, ${getColor(0.2)}, ${getColor(0.8)})` }} />
          <div className="flex items-center gap-2">
            <span>Water Front</span>
            <div className="w-3 h-3 rounded-sm border border-slate-700" style={{ backgroundColor: getColor(1 - (params.snr || 0.2)) }} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default SimulationHeatmap;
