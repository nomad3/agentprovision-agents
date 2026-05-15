import { useNavigate } from 'react-router-dom';

const WorkflowsPanel = () => {
  const navigate = useNavigate();
  return (
    <>
      <div className="ap-sidebar-cta">
        <button type="button" onClick={() => navigate('/workflows/builder')}>+ New workflow</button>
      </div>
      <ul className="ap-sidebar-list">
        <li>
          <button type="button" onClick={() => navigate('/workflows')}>All workflows</button>
        </li>
        <li>
          <button type="button" onClick={() => navigate('/workflows?tab=executions')}>Recent runs</button>
        </li>
      </ul>
    </>
  );
};

export default WorkflowsPanel;
