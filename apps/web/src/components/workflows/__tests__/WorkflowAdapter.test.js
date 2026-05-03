import { definitionToFlow, flowToDefinition } from '../WorkflowAdapter';

describe('WorkflowAdapter.definitionToFlow', () => {
  test('renders a trigger root even with no steps', () => {
    const { nodes, edges } = definitionToFlow({ steps: [] }, { type: 'manual' });
    expect(nodes).toHaveLength(1);
    expect(nodes[0]).toMatchObject({ id: 'trigger-root', type: 'triggerNode' });
    expect(edges).toEqual([]);
  });

  test('uses provided trigger config', () => {
    const { nodes } = definitionToFlow(
      { steps: [] },
      { type: 'cron', cron: '0 9 * * *' }
    );
    expect(nodes[0].data.trigger).toEqual({ type: 'cron', cron: '0 9 * * *' });
  });

  test('defaults to manual trigger when omitted', () => {
    const { nodes } = definitionToFlow({ steps: [] });
    expect(nodes[0].data.trigger).toEqual({ type: 'manual' });
  });

  test('emits a stepNode + edge for a single mcp_tool step', () => {
    const def = { steps: [{ id: 's1', type: 'mcp_tool', tool: 'gmail.send' }] };
    const { nodes, edges } = definitionToFlow(def);
    expect(nodes).toHaveLength(2);
    const stepNode = nodes.find((n) => n.id === 's1');
    expect(stepNode.type).toBe('stepNode');
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({ source: 'trigger-root', target: 's1' });
  });

  test('maps step types to node types correctly', () => {
    const def = {
      steps: [
        { id: 'c1', type: 'condition' },
        { id: 'fe1', type: 'for_each' },
        { id: 'p1', type: 'parallel' },
        { id: 'a1', type: 'human_approval' },
      ],
    };
    const { nodes } = definitionToFlow(def);
    expect(nodes.find((n) => n.id === 'c1').type).toBe('conditionNode');
    expect(nodes.find((n) => n.id === 'fe1').type).toBe('forEachNode');
    expect(nodes.find((n) => n.id === 'p1').type).toBe('parallelNode');
    expect(nodes.find((n) => n.id === 'a1').type).toBe('approvalNode');
  });

  test('emits then/else edges with handle ids for condition steps', () => {
    const def = {
      steps: [
        { id: 'cond', type: 'condition', then: 'yes-step', else: 'no-step' },
        { id: 'yes-step', type: 'mcp_tool' },
        { id: 'no-step', type: 'mcp_tool' },
      ],
    };
    const { edges } = definitionToFlow(def);
    const thenEdge = edges.find((e) => e.sourceHandle === 'then');
    const elseEdge = edges.find((e) => e.sourceHandle === 'else');
    expect(thenEdge).toBeDefined();
    expect(thenEdge.target).toBe('yes-step');
    expect(elseEdge).toBeDefined();
    expect(elseEdge.target).toBe('no-step');
  });

  test('skips else edge when else === "skip"', () => {
    const def = {
      steps: [
        { id: 'cond', type: 'condition', then: 't1', else: 'skip' },
        { id: 't1', type: 'mcp_tool' },
      ],
    };
    const { edges } = definitionToFlow(def);
    expect(edges.find((e) => e.sourceHandle === 'else')).toBeUndefined();
  });

  test('parallel steps emit a synthetic merge node', () => {
    const def = {
      steps: [
        {
          id: 'fork',
          type: 'parallel',
          steps: [
            { id: 'a', type: 'mcp_tool' },
            { id: 'b', type: 'mcp_tool' },
          ],
        },
      ],
    };
    const { nodes, edges } = definitionToFlow(def);
    expect(nodes.some((n) => n.id === 'merge-fork')).toBe(true);
    expect(edges.some((e) => e.source === 'a' && e.target === 'merge-fork')).toBe(true);
    expect(edges.some((e) => e.source === 'b' && e.target === 'merge-fork')).toBe(true);
  });

  test('for_each step links its sub-steps as a chain off the for_each node', () => {
    const def = {
      steps: [
        {
          id: 'fe',
          type: 'for_each',
          steps: [{ id: 'inner', type: 'mcp_tool' }],
        },
      ],
    };
    const { edges } = definitionToFlow(def);
    expect(edges.some((e) => e.source === 'fe' && e.target === 'inner')).toBe(true);
  });

  test('applies a layout (positions are non-zero)', () => {
    const def = { steps: [{ id: 's1', type: 'mcp_tool' }] };
    const { nodes } = definitionToFlow(def);
    const stepNode = nodes.find((n) => n.id === 's1');
    expect(typeof stepNode.position.x).toBe('number');
    expect(typeof stepNode.position.y).toBe('number');
  });
});

describe('WorkflowAdapter.flowToDefinition', () => {
  test('extracts trigger config from the trigger node', () => {
    const nodes = [
      {
        id: 'trigger-root',
        type: 'triggerNode',
        data: { trigger: { type: 'webhook', path: '/wh' } },
      },
    ];
    const { triggerConfig } = flowToDefinition(nodes, []);
    expect(triggerConfig).toEqual({ type: 'webhook', path: '/wh' });
  });

  test('falls back to manual when no trigger present', () => {
    const { triggerConfig } = flowToDefinition([], []);
    expect(triggerConfig).toEqual({ type: 'manual' });
  });

  test('round-trips a simple linear definition', () => {
    const def = {
      steps: [
        { id: 's1', type: 'mcp_tool', tool: 'gmail.send' },
        { id: 's2', type: 'transform', operation: 'json' },
      ],
    };
    const flow = definitionToFlow(def, { type: 'manual' });
    const back = flowToDefinition(flow.nodes, flow.edges);
    expect(back.definition.steps.map((s) => s.id)).toEqual(['s1', 's2']);
    expect(back.definition.steps[0].tool).toBe('gmail.send');
    expect(back.definition.steps[1].operation).toBe('json');
  });

  test('round-trips condition then/else handles', () => {
    const def = {
      steps: [
        { id: 'cond', type: 'condition', expression: 'x>0', then: 'a', else: 'b' },
        { id: 'a', type: 'mcp_tool' },
        { id: 'b', type: 'mcp_tool' },
      ],
    };
    const flow = definitionToFlow(def, { type: 'manual' });
    const back = flowToDefinition(flow.nodes, flow.edges);
    const condStep = back.definition.steps.find((s) => s.id === 'cond');
    expect(condStep.then).toBe('a');
    expect(condStep.else).toBe('b');
  });

  test('round-trips parallel sub-steps', () => {
    const def = {
      steps: [
        {
          id: 'fork',
          type: 'parallel',
          steps: [
            { id: 'a', type: 'mcp_tool' },
            { id: 'b', type: 'mcp_tool' },
          ],
        },
      ],
    };
    const flow = definitionToFlow(def, { type: 'manual' });
    const back = flowToDefinition(flow.nodes, flow.edges);
    const fork = back.definition.steps.find((s) => s.id === 'fork');
    expect(fork.steps.map((s) => s.id).sort()).toEqual(['a', 'b']);
  });
});
