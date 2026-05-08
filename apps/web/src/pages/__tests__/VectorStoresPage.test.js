import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import VectorStoresPage from '../VectorStoresPage';

jest.mock('../../services/vectorStore', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    remove: jest.fn(),
  },
}));
jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const vectorStoreService = require('../../services/vectorStore').default;

const sampleStores = [
  { id: 'vs-1', name: 'Customer Embeddings', description: 'Customer profile vectors', config: { dim: 768 } },
  { id: 'vs-2', name: 'Product Catalog', description: 'Product description vectors', config: { dim: 384 } },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <VectorStoresPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  vectorStoreService.getAll.mockResolvedValue({ data: sampleStores });
  vectorStoreService.create.mockResolvedValue({});
  vectorStoreService.update.mockResolvedValue({});
  vectorStoreService.remove.mockResolvedValue({});
});

describe('VectorStoresPage', () => {
  test('loads and renders the vector stores table', async () => {
    renderPage();
    await waitFor(() => expect(vectorStoreService.getAll).toHaveBeenCalled());
    expect(await screen.findByText('Customer Embeddings')).toBeInTheDocument();
    expect(screen.getByText('Product Catalog')).toBeInTheDocument();
  });

  test('shows the empty-state when no stores exist', async () => {
    vectorStoreService.getAll.mockResolvedValue({ data: [] });
    renderPage();
    await waitFor(() => expect(vectorStoreService.getAll).toHaveBeenCalled());
    // Two "addStore" buttons render in the empty state — header + body.
    const addButtons = screen.getAllByRole('button', { name: /vectorStores\.addStore/ });
    expect(addButtons.length).toBeGreaterThanOrEqual(2);
  });

  test('opens the add-store modal when clicking the header button', async () => {
    vectorStoreService.getAll.mockResolvedValue({ data: [] });
    renderPage();
    const addButtons = await screen.findAllByRole('button', { name: /vectorStores\.addStore/ });
    fireEvent.click(addButtons[0]);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  test('creating a new store calls service.create with parsed config', async () => {
    vectorStoreService.getAll.mockResolvedValue({ data: [] });
    renderPage();
    const addButtons = await screen.findAllByRole('button', { name: /vectorStores\.addStore/ });
    fireEvent.click(addButtons[0]);
    const dialog = await screen.findByRole('dialog');
    // First textbox is name, second is description, third (textarea) is config.
    const inputs = within(dialog).getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { name: 'name', value: 'Test Store' } });
    fireEvent.change(inputs[1], { target: { name: 'description', value: 'Hello' } });
    fireEvent.change(inputs[2], { target: { name: 'config', value: '{"dim": 512}' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /vectorStores\.modal\.save/ }));
    await waitFor(() => {
      expect(vectorStoreService.create).toHaveBeenCalledWith({
        name: 'Test Store',
        description: 'Hello',
        config: { dim: 512 },
      });
    });
  });

  test('shows a save error when config JSON is invalid', async () => {
    vectorStoreService.getAll.mockResolvedValue({ data: [] });
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    const addButtons = await screen.findAllByRole('button', { name: /vectorStores\.addStore/ });
    fireEvent.click(addButtons[0]);
    const dialog = await screen.findByRole('dialog');
    const inputs = within(dialog).getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { name: 'name', value: 'Bad Store' } });
    fireEvent.change(inputs[2], { target: { name: 'config', value: 'not-valid-json' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /vectorStores\.modal\.save/ }));
    expect(await screen.findByText('vectorStores.errors.save')).toBeInTheDocument();
    errSpy.mockRestore();
  });

  test('Edit button pre-populates the modal with existing values', async () => {
    renderPage();
    await screen.findByText('Customer Embeddings');
    const editBtns = screen.getAllByRole('button', { name: /vectorStores\.actions\.edit/ });
    fireEvent.click(editBtns[0]);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByDisplayValue('Customer Embeddings')).toBeInTheDocument();
  });

  test('Delete button confirms and calls remove', async () => {
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();
    await screen.findByText('Customer Embeddings');
    const deleteBtns = screen.getAllByRole('button', { name: /vectorStores\.actions\.delete/ });
    fireEvent.click(deleteBtns[0]);
    await waitFor(() => expect(vectorStoreService.remove).toHaveBeenCalledWith('vs-1'));
    confirmSpy.mockRestore();
  });

  test('shows an error alert if getAll fails', async () => {
    vectorStoreService.getAll.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    expect(await screen.findByText('vectorStores.errors.fetch')).toBeInTheDocument();
    errSpy.mockRestore();
  });
});
