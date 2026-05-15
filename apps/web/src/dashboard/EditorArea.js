import { FaTimes } from 'react-icons/fa';
import ChatTab from './tabs/ChatTab';
import EmptyTab from './tabs/EmptyTab';
import './EditorArea.css';

const TAB_RENDERERS = {
  chat: ChatTab,
};

const EditorArea = ({ tabsApi }) => {
  const { tabs, activeId, activateTab, closeTab, activeTab } = tabsApi;
  const Renderer = activeTab && TAB_RENDERERS[activeTab.kind];

  return (
    <div className="ap-editor">
      <div className="ap-editor-tabbar">
        {tabs.length === 0 ? (
          <span className="ap-editor-tabbar-empty">No tabs open — pick a session from the sidebar</span>
        ) : (
          tabs.map((t) => (
            <div
              key={t.id}
              className={`ap-editor-tab ${activeId === t.id ? 'active' : ''}`}
              role="tab"
              aria-selected={activeId === t.id}
              onClick={() => activateTab(t.id)}
            >
              <span className="ap-editor-tab-title" title={t.title}>{t.title}</span>
              <button
                type="button"
                className="ap-editor-tab-close"
                aria-label="Close tab"
                onClick={(e) => { e.stopPropagation(); closeTab(t.id); }}
              >
                <FaTimes size={10} />
              </button>
            </div>
          ))
        )}
      </div>
      <div className="ap-editor-body">
        {activeTab && Renderer ? (
          <Renderer tab={activeTab} />
        ) : (
          <EmptyTab />
        )}
      </div>
    </div>
  );
};

export default EditorArea;
