import pandas as pd
df = pd.read_csv("albums.csv")
df2 = pd.DataFrame(df.Description.unique()).to_csv("test.csv")
