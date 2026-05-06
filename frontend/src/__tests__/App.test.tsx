import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../App';

describe('App', () => {
  it('renders the main dashboard heading or auth screen', () => {
    render(<App />);
    expect(screen.getByText(/Hviel \| PRC AI Hub/i)).toBeInTheDocument();
  });

  it('renders the auth screen initially', () => {
    render(<App />);
    expect(screen.getByText('Authenticate Session')).toBeInTheDocument();
  });
});
