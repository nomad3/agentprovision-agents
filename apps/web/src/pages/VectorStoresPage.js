import React, { useState, useEffect } from 'react';
import { Table, Modal, Form, Alert } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import Layout from '../components/Layout';
import vectorStoreService from '../services/vectorStore';

const VectorStoresPage = () => {
  const { t } = useTranslation('tools');
  const [vectorStores, setVectorStores] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [editingVectorStore, setEditingVectorStore] = useState(null);
  const [formData, setFormData] = useState({ name: '', description: '', config: '{}' });
  const [error, setError] = useState('');

  useEffect(() => {
    fetchVectorStores();
  }, []);

  const fetchVectorStores = async () => {
    try {
      const response = await vectorStoreService.getAll();
      setVectorStores(response.data);
    } catch (err) {
      setError(t('vectorStores.errors.fetch'));
      console.error(err);
    }
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setEditingVectorStore(null);
    setFormData({ name: '', description: '', config: '{}' });
    setError('');
  };

  const handleShowModal = (vectorStore = null) => {
    if (vectorStore) {
      setEditingVectorStore(vectorStore);
      setFormData({ name: vectorStore.name, description: vectorStore.description, config: JSON.stringify(vectorStore.config, null, 2) });
    } else {
      setEditingVectorStore(null);
      setFormData({ name: '', description: '', config: '{}' });
    }
    setShowModal(true);
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData({ ...formData, [name]: value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const config = JSON.parse(formData.config);
      const data = { ...formData, config };

      if (editingVectorStore) {
        await vectorStoreService.update(editingVectorStore.id, data);
      } else {
        await vectorStoreService.create(data);
      }
      fetchVectorStores();
      handleCloseModal();
    } catch (err) {
      setError(t('vectorStores.errors.save'));
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (window.confirm(t('vectorStores.deleteConfirm'))) {
      try {
        await vectorStoreService.remove(id);
        fetchVectorStores();
      } catch (err) {
        setError(t('vectorStores.errors.delete'));
        console.error(err);
      }
    }
  };

  return (
    <Layout>
      <header className="ap-page-header">
        <div>
          <h1 className="ap-page-title">{t('vectorStores.title')}</h1>
        </div>
        <div className="ap-page-actions">
          <button type="button" className="ap-btn-primary" onClick={() => handleShowModal()}>
            {t('vectorStores.addStore')}
          </button>
        </div>
      </header>

      {error && <Alert variant="danger">{error}</Alert>}

      {vectorStores.length === 0 ? (
        <div className="ap-empty">
          <div className="ap-empty-title">{t('vectorStores.title')}</div>
          <div className="ap-empty-text">—</div>
          <button type="button" className="ap-btn-primary" onClick={() => handleShowModal()}>
            {t('vectorStores.addStore')}
          </button>
        </div>
      ) : (
        <article className="ap-card">
          <Table hover responsive className="ap-table mb-0">
            <thead>
              <tr>
                <th>{t('vectorStores.table.name')}</th>
                <th>{t('vectorStores.table.description')}</th>
                <th>{t('vectorStores.table.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {vectorStores.map((vs) => (
                <tr key={vs.id}>
                  <td>{vs.name}</td>
                  <td>{vs.description}</td>
                  <td>
                    <button type="button" className="ap-btn-secondary ap-btn-sm" onClick={() => handleShowModal(vs)}>
                      {t('vectorStores.actions.edit')}
                    </button>{' '}
                    <button type="button" className="ap-btn-danger ap-btn-sm" onClick={() => handleDelete(vs.id)}>
                      {t('vectorStores.actions.delete')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </article>
      )}

      <Modal show={showModal} onHide={handleCloseModal}>
        <Modal.Header closeButton>
          <Modal.Title>{editingVectorStore ? t('vectorStores.modal.editTitle') : t('vectorStores.modal.addTitle')}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={handleSubmit}>
            <Form.Group className="mb-3">
              <Form.Label>{t('vectorStores.modal.name')}</Form.Label>
              <Form.Control type="text" name="name" value={formData.name} onChange={handleChange} required />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>{t('vectorStores.modal.description')}</Form.Label>
              <Form.Control type="text" name="description" value={formData.description} onChange={handleChange} />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>{t('vectorStores.modal.config')}</Form.Label>
              <Form.Control as="textarea" rows={5} name="config" value={formData.config} onChange={handleChange} required />
            </Form.Group>
            <button type="submit" className="ap-btn-primary">{t('vectorStores.modal.save')}</button>
          </Form>
        </Modal.Body>
      </Modal>
    </Layout>
  );
};

export default VectorStoresPage;
