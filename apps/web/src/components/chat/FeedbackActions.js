import { useState } from 'react';
import { Button, ButtonGroup, Dropdown } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import learningService from '../../services/learningService';

const FeedbackActions = ({ trajectoryId, stepIndex }) => {
  const { t } = useTranslation('learning');
  const [submitted, setSubmitted] = useState(null);

  const handleFeedback = async (feedbackType) => {
    try {
      await learningService.submitFeedback({
        trajectory_id: trajectoryId,
        step_index: stepIndex,
        feedback_type: feedbackType,
      });
      setSubmitted(feedbackType);
    } catch (err) {
      console.error('Feedback submission failed:', err);
    }
  };

  if (submitted) {
    return (
      <small className="text-muted ms-2">
        {submitted === 'thumbs_up' ? '👍' : submitted === 'thumbs_down' ? '👎' : '🚩'}{' '}
        {t('feedback.submitted', 'Submitted')}
      </small>
    );
  }

  return (
    <div className="d-inline-flex align-items-center ms-2" style={{ opacity: 0.6 }}>
      <ButtonGroup size="sm">
        <Button
          variant="outline-secondary"
          size="sm"
          onClick={() => handleFeedback('thumbs_up')}
          title={t('feedback.thumbsUp', 'Helpful')}
        >
          👍
        </Button>
        <Button
          variant="outline-secondary"
          size="sm"
          onClick={() => handleFeedback('thumbs_down')}
          title={t('feedback.thumbsDown', 'Not helpful')}
        >
          👎
        </Button>
      </ButtonGroup>
      <Dropdown className="ms-1">
        <Dropdown.Toggle variant="outline-secondary" size="sm" id="feedback-flag">
          🚩
        </Dropdown.Toggle>
        <Dropdown.Menu>
          <Dropdown.Item onClick={() => handleFeedback('wrong_agent')}>
            {t('feedback.wrongAgent', 'Wrong agent')}
          </Dropdown.Item>
          <Dropdown.Item onClick={() => handleFeedback('memory_irrelevant')}>
            {t('feedback.irrelevantMemory', 'Irrelevant memory')}
          </Dropdown.Item>
          <Dropdown.Item onClick={() => handleFeedback('flag_issue')}>
            {t('feedback.flagIssue', 'Flag issue')}
          </Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown>
    </div>
  );
};

export default FeedbackActions;
