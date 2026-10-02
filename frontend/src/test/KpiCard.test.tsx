import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import KpiCard from '../components/KpiCard';

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('KpiCard', () => {
  it('shows label and value', () => {
    wrap(<KpiCard label="Active Vehicles" value={42} sub="of 500" />);
    expect(screen.getByText('Active Vehicles')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('of 500')).toBeInTheDocument();
  });

  it('renders dash for missing values', () => {
    wrap(<KpiCard label="On-Time Rate" value="—" />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
