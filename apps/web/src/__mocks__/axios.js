// Manual mock for axios to avoid ESM import issues in jest (CRA + jsdom).
// Tests that need specific behavior can override the default with
// jest.spyOn or by reassigning the returned methods.

const okResponse = (data = {}) => Promise.resolve({ data, status: 200, headers: {} });

const interceptorRegistry = () => ({
  use: jest.fn(),
  eject: jest.fn(),
});

const baseInstance = () => {
  const inst = jest.fn(() => okResponse());
  inst.get = jest.fn(() => okResponse());
  inst.post = jest.fn(() => okResponse());
  inst.put = jest.fn(() => okResponse());
  inst.patch = jest.fn(() => okResponse());
  inst.delete = jest.fn(() => okResponse());
  inst.head = jest.fn(() => okResponse());
  inst.options = jest.fn(() => okResponse());
  inst.request = jest.fn(() => okResponse());
  inst.interceptors = {
    request: interceptorRegistry(),
    response: interceptorRegistry(),
  };
  inst.defaults = { headers: { common: {} } };
  return inst;
};

const axios = baseInstance();
axios.create = jest.fn(() => baseInstance());
axios.CancelToken = {
  source: () => ({ token: 'mock-token', cancel: jest.fn() }),
};
axios.isCancel = jest.fn(() => false);
axios.isAxiosError = jest.fn(() => false);

module.exports = axios;
module.exports.default = axios;
