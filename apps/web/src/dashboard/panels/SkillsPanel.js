import { useNavigate } from 'react-router-dom';

const SkillsPanel = () => {
  const navigate = useNavigate();
  return (
    <>
      <div className="ap-sidebar-cta">
        <button type="button" onClick={() => navigate('/skills')}>Open library</button>
      </div>
      <div className="ap-sidebar-empty">
        Skill list inline in Phase 2. Open the library to browse or author.
      </div>
    </>
  );
};

export default SkillsPanel;
