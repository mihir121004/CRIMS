# PyMySQL shim: Vercel cannot compile mysqlclient; use PyMySQL as MySQLdb drop-in.
try:
    import pymysql
    pymysql.version_info = (2, 2, 8, "final", 0)  # satisfy Django's driver check
    pymysql.install_as_MySQLdb()
except ImportError:
    pass
