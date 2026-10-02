import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import StatusBadge from '../components/StatusBadge';

describe('StatusBadge', () => {
  it('renders delivered status with correct text', () => {
    render(<StatusBadge status="DELIVERED" />);
    expect(screen.getByText('DELIVERED')).toBeInTheDocument();
  });

  it('renders unknown status without crashing', () => {
    render(<StatusBadge status="SOMETHING_ELSE" />);
    expect(screen.getByText('SOMETHING_ELSE')).toBeInTheDocument();
  });
});
