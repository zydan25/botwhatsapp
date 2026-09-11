module.exports = {
  apps: [
    {
      name: 'waseliyat',
      cwd: '/home/root/projects/waseliyat',
      script: '/home/root/projects/waseliyat/.venv/bin/python',
      args: 'run.py',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '512M',
      time: true,
      env: {
        PYTHONUNBUFFERED: '1',
        FLASK_ENV: 'production',
      },
    },
  ],
};
