import React from 'react';
import Layout from '../components/Layout';

const DeploymentsPage = () => {
  return (
    <Layout>
      <header className="ap-page-header">
        <div>
          <h1 className="ap-page-title">Deployments</h1>
          <p className="ap-page-subtitle">Manage your deployments here.</p>
        </div>
      </header>
    </Layout>
  );
};

export default DeploymentsPage;
