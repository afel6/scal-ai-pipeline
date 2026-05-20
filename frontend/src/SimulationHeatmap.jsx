/* eslint-disable no-unused-vars, react-hooks/set-state-in-effect */
import React, { useState, useEffect } from 'react';
import { Play, Pause, FastForward, Activity } from 'lucide-react';

const SimulationHeatmap = ({ content }) => {
  const [parsedData, setParsedData] = useState(null);
  const [parseError, setParseError] = useState(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  // Parse incoming content and fetch file if needed
  useEffect(() => {
    setCurrentStep(0);
    setIsPlaying(false);
    setParsedData(null);
    setParseError(null);
    
    if (!content) return;
    
    try {
      const parsed = JSON.parse(content);
      if (parsed.status === 'success') {
        if (parsed.file_path) {
          // It's a reference to a temporary file
          const API_URL = import.meta.env.VITE_API_URL || '';
          fetch(`${API_URL}${parsed.file_path}`)
            .then(res => {
              if (!res.ok) throw new Error("Network response was not ok");
              return res.json();
            })
            .then(data => {
              setParsedData(data);
            })
            .catch(err => {
              setParseError("Failed to fetch simulation data file.");
            });
        } else if (parsed.mode === '2d' || parsed.history) {
          setParsedData(parsed);
        } else {
          setParseError("Invalid simulation data format.");
        }
      } else {
        setParseError("Simulation status was not successful.");
      }
    } catch (_err) {
      setParseError("Failed to parse simulation output.");
    }
  }, [content]);

  const data = parsedData;
  const error = parseError;

  useEffect(() => {
    let interval;
    if (isPlaying && data && data.history && currentStep < data.history.length - 1) {
      interval = setInterval(() => {
        setCurrentStep(prev => {
          if (prev >= data.history.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 500); // 500ms per frame
    }
    return () => clearInterval(interval);
  }, [isPlaying, currentStep, data]);

  if (error) {
    return (
      <div className="p-4 bg-red-950/20 border border-red-900/30 rounded-2xl text-red-400 text-sm font-mono my-4">
        {error}
      </div>
    );
  }

  if (!data) return null;

  const { history = [], params = {} } = data;
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
    <div className="my-8 bg-[#0c0c12]/90 backdrop-blur-xl border border-yellow-500/20 rounded-[2rem] overflow-hidden shadow-[0_24px_60px_-15px_rgba(0,0,0,0.8),inset_0_1px_1px_rgba(255,255,255,0.05)] animate-fade-in">
      {/* Header */}
      <div className="bg-gradient-to-r from-yellow-950/30 to-transparent px-6 py-4 flex items-center justify-between border-b border-white/5">
        <div className="flex items-center gap-2.5">
          <div className="relative flex items-center justify-center">
            <span className="absolute w-2 h-2 rounded-full bg-yellow-500 animate-ping opacity-75" />
            <span className="relative w-2.5 h-2.5 rounded-full bg-yellow-500" />
          </div>
          <h3 className="text-yellow-400 font-black tracking-[0.2em] text-[11px] uppercase">
            2D Saturation Front Simulator
          </h3>
        </div>
        <div className="text-slate-400 text-[10px] font-mono bg-white/5 border border-white/5 px-2.5 py-1 rounded-full">
          GRID: <span className="text-yellow-400 font-bold">{nx}x{ny}</span> &nbsp;|&nbsp; MODEL: <span className="text-white font-bold">{params.model?.toUpperCase()}</span>
        </div>
      </div>

      {/* Main Heatmap Area */}
      <div className="p-8 flex flex-col items-center bg-black/40">
        <div 
          className="grid gap-[1px] bg-slate-800/80 p-1 border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
          style={{ 
            gridTemplateColumns: `repeat(${ny}, minmax(0, 1fr))`,
            width: '100%',
            maxWidth: '380px',
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
      <div className="bg-[#111116]/80 p-6 border-t border-white/5">
        <div className="flex items-center gap-5 mb-4">
          <button 
            onClick={() => {
              if (currentStep >= history.length - 1) setCurrentStep(0);
              setIsPlaying(!isPlaying);
            }}
            className="w-12 h-12 rounded-full bg-gradient-to-br from-yellow-400 to-amber-600 hover:from-yellow-300 hover:to-amber-500 text-black flex items-center justify-center transition-all duration-300 active:scale-95 hover:scale-105 hover:shadow-[0_0_20px_rgba(251,191,36,0.4)] shadow-lg shrink-0"
          >
            {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current ml-1" />}
          </button>
          
          <div className="flex-1 flex flex-col gap-2">
            <div className="flex justify-between text-[10px] font-mono text-slate-500">
              <span className="uppercase tracking-wider">Start</span>
              <span className="text-yellow-400 font-bold bg-yellow-500/10 px-2 py-0.5 rounded-full border border-yellow-500/20">Step {currentStep} / {Math.max(history.length - 1, 0)}</span>
              <span className="uppercase tracking-wider">End</span>
            </div>
            <input 
              type="range" 
              min="0" 
              max={Math.max(history.length - 1, 0)}
              value={currentStep}
              onChange={(e) => {
                setCurrentStep(parseInt(e.target.value));
                setIsPlaying(false);
              }}
              className="w-full h-2 bg-slate-800 rounded-full appearance-none cursor-pointer accent-yellow-500 focus:outline-none"
            />
          </div>
          
          <button 
            onClick={() => setCurrentStep(history.length - 1)}
            className="w-10 h-10 rounded-full bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 text-slate-300 hover:text-white flex items-center justify-center transition-all shrink-0 active:scale-95"
            title="Skip to end"
          >
            <FastForward className="w-4 h-4 fill-current" />
          </button>
        </div>
        
        {/* Legend */}
        <div className="flex items-center justify-between text-[10px] font-mono uppercase text-slate-400 px-1 mt-4 border-t border-white/5 pt-4">
          <div className="flex items-center gap-2">
            <div className="w-3.5 h-3.5 rounded-full border border-white/20" style={{ backgroundColor: getColor(params.swr || 0.2) }} />
            <span className="text-slate-500 tracking-wider">Residual Water</span>
          </div>
          <div className="flex-1 h-2 mx-5 rounded-full shadow-inner" style={{ background: `linear-gradient(to right, ${getColor(0.2)}, ${getColor(0.8)})` }} />
          <div className="flex items-center gap-2">
            <span className="text-slate-500 tracking-wider">Water Front</span>
            <div className="w-3.5 h-3.5 rounded-full border border-white/20" style={{ backgroundColor: getColor(1 - (params.snr || 0.2)) }} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default SimulationHeatmap;
