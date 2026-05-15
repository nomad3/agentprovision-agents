import { useNavigate } from 'react-router-dom';

const IntegrationsPanel = () => {
  const navigate = useNavigate();
  // Phase 1: keep integrations simple — link into the existing rich
  // IntegrationsPage which already has connection management, OAuth
  // flows, datasets, and AI models tabs. Phase 2 will inline a live
  // status indicator for each connector here.
  return (
    <>
      <div className="ap-sidebar-cta">
        <button type="button" onClick={() => navigate('/integrations')}>+ Connect new</button>
      </div>
      <ul className="ap-sidebar-list">
        <li>
          <button type="button" onClick={() => navigate('/integrations')}>Connectors</button>
        </li>
        <li>
          <button type="button" onClick={() => navigate('/integrations?tab=data-sources')}>Data sources</button>
        </li>
        <li>
          <button type="button" onClick={() => navigate('/integrations?tab=datasets')}>Datasets</button>
        </li>
        <li>
          <button type="button" onClick={() => navigate('/integrations?tab=ai-models')}>AI models</button>
        </li>
      </ul>
    </>
  );
};

export default IntegrationsPanel;
