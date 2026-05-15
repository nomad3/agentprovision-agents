import { Link } from 'react-router-dom';

const EmptyTab = () => (
  <div className="ap-editor-empty">
    <div className="ap-editor-empty-title">Welcome to Alpha Control</div>
    <div className="ap-editor-empty-hint">
      Pick a chat session from the left, or browse agents, memory, skills, workflows, and integrations.
    </div>
    <div className="ap-editor-empty-hint">
      Need the old single-page chat? <Link to="/chat">Open /chat</Link>
    </div>
  </div>
);

export default EmptyTab;
