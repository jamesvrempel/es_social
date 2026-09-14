from setuptools import setup, find_packages

with open("es_social/__init__.py") as f:
    for line in f:
        if line.startswith("__version__"):
            version = line.split("=")[1].strip().strip('"').strip("'")
            break

setup(
    name="es_social",
    version=version,
    description="Public social network module for Frappe / ERPNext (ES Social)",
    author="Enterprise Systems Australia",
    author_email="james@enterprisesystems.com.au",
    url="https://github.com/jamesvrempel/es_social",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=[],
)
