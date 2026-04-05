from setuptools import setup, find_packages

setup(
    name='oyelakin',
    version='1.0.0',
    description='A production-grade automated trading system for the Deriv platform with backtesting, AI signal filtering, and a real-time web dashboard',
    author='younlec',
    packages=find_packages(),
    python_requires='>=3.8',
    install_requires=[
        'python-deriv-api',
        'pandas',
        'numpy',
        'ta',
        'scikit-learn',
        'fastapi',
        'uvicorn',
        'python-dotenv',
        'websockets',
        'python-multipart'
    ],
)