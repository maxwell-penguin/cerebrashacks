import { useState } from 'react';

const trackEvent = (eventName, data) => {
  // Lightweight analytics stub
  console.log('Analytics Event:', eventName, data);
};

function App() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    trackEvent('login_submit', { email });
    alert(`Email: ${email}\nPassword: ${password}`);
  };

  const handleEmailChange = (e) => {
    const value = e.target.value;
    setEmail(value);
    trackEvent('email_change', { value });
  };

  const handlePasswordChange = (e) => {
    const value = e.target.value;
    setPassword(value);
    trackEvent('password_change', { value });
  };

  return (
    <main className="flex items-center justify-center min-h-screen bg-gray-50" role="main">
      <section className="w-full max-w-sm p-6 bg-white rounded-lg shadow" role="region" aria-labelledby="login-heading">
        <h1 id="login-heading" className="text-2xl font-bold text-center mb-4">Login</h1>
        <form
          onSubmit={handleSubmit}
          className="flex flex-col space-y-4"
          role="form"
          aria-label="Login form"
        >
          <label className="block" htmlFor="email-input">
            <span className="sr-only">Email</span>
            <input
              id="email-input"
              type="email"
              placeholder="Email"
              aria-label="Email address"
              value={email}
              onChange={handleEmailChange}
              className="w-full border rounded p-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </label>
          <label className="block" htmlFor="password-input">
            <span className="sr-only">Password</span>
            <input
              id="password-input"
              type="password"
              placeholder="Password"
              aria-label="Password"
              value={password}
              onChange={handlePasswordChange}
              className="w-full border rounded p-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </label>
          <button
            type="submit"
            className="w-full md:w-1/2 mx-auto bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 rounded"
            aria-label="Sign in"
            onClick={() => trackEvent('sign_in_click', { email })}
          >
            Sign In
          </button>
        </form>
      </section>
    </main>
  );
}

export default App;
