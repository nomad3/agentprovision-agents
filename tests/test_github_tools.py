import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from tools.github_tools import create_branch, commit_and_push, create_pull_request, check_pr_status
from config.settings import settings

@pytest.mark.asyncio
@patch('tools.github_tools.execute_shell')
async def test_create_branch(mock_execute):
    mock_execute.return_value = {"return_code": 0, "stdout": "", "stderr": ""}
    result = await create_branch("test-branch")
    mock_execute.assert_called_once_with("git checkout -b test-branch", working_dir="/app")
    assert result["status"] == "success"

@pytest.mark.asyncio
@patch('tools.github_tools.execute_shell')
async def test_commit_and_push(mock_execute):
    mock_execute.return_value = {"return_code": 0, "stdout": "", "stderr": ""}
    result = await commit_and_push("test-branch", "Test message", files=["test.py"])
    assert mock_execute.call_count == 3
    assert result["status"] == "success"

@pytest.mark.asyncio
@patch('tools.github_tools._get_github_client')
async def test_create_pull_request(mock_get_client):
    settings.github_token = "fake-token"
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"html_url": "http://example.com/pr/1", "number": 1}
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    
    mock_get_client.return_value = mock_client
    
    result = await create_pull_request("Test PR", "Body", "test-branch")
    assert result["status"] == "success"
    assert result["pr_number"] == 1
    
@pytest.mark.asyncio
@patch('tools.github_tools._get_github_client')
async def test_check_pr_status(mock_get_client):
    settings.github_token = "fake-token"
    mock_client = AsyncMock()
    
    mock_pr_response = MagicMock()
    mock_pr_response.status_code = 200
    mock_pr_response.json.return_value = {"head": {"sha": "abcdef"}}
    
    mock_checks_response = MagicMock()
    mock_checks_response.status_code = 200
    mock_checks_response.json.return_value = {"check_runs": [{"name": "test", "status": "completed"}]}
    
    mock_client.get.side_effect = [mock_pr_response, mock_checks_response]
    mock_client.__aenter__.return_value = mock_client
    
    mock_get_client.return_value = mock_client
    
    result = await check_pr_status(1)
    assert result["status"] == "success"
    assert len(result["checks"]) == 1

