from flask import Flask, request, jsonify
import pandas as pd
import json
import time
from collections import Counter
import datetime
from datetime import datetime, timedelta
from dateutil.parser import parse
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import pandas as pd
import requests
import numpy as np
from flask import Flask, jsonify, request
import uuid
from collections import OrderedDict

# from collections import OrderedDict

app = Flask(__name__)

# Load configuration from a JSON file
with open("config.json", "r") as config_file:
    config_data = json.load(config_file)

# AWS Configurations
AWS_ACCESS_KEY_ID = config_data["aws"]["aws_access_key_id"]

AWS_SECRET_ACCESS_KEY = config_data["aws"]["aws_secret_access_key"]

REGION_NAME = config_data["aws"]["region_name"]

BUCKET_NAME = config_data["aws"]["bucket_name"]

# API Configurations (if needed elsewhere in the script)
# X_API_KEY = config_data["api"]["x-api-key"]
# X_API_SECRET = config_data["api"]["x-api-secret"]

# Athena Configurations
ATHENA_S3_OUTPUT = config_data["athena"]["s3_output_location"]


session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=REGION_NAME  # this should be the region you're trying to create a bucket in
)


def upload_file_to_s3(file_name, bucket_name, s3_file_path):
    s3 = session.client('s3')
    try:
        s3.upload_file(file_name, bucket_name, s3_file_path)
        print("Upload Successful")
        return True
    except FileNotFoundError:
        print("The file was not found")
        return False
    except NoCredentialsError:
        print("Credentials not available")
        return False
    except ClientError as e:
        print(f"An unexpected error occurred: {e}")
        return False

def run_athena_query(database,query):
    """
    Query Athena and return the results as a DataFrame.

    :param database: The Athena database to query.
    :param query: The SQL query string.
    :return: DataFrame with the query results.
    """
    client = boto3.client('athena',
                          region_name=REGION_NAME,
                          aws_access_key_id=AWS_ACCESS_KEY_ID,
                          aws_secret_access_key=AWS_SECRET_ACCESS_KEY)

    # Start the Athena query execution
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': database
        },
        ResultConfiguration={
            'OutputLocation': ATHENA_S3_OUTPUT
        }
    )

    query_execution_id = response['QueryExecutionId']
    for _ in range(10):  # Max attempts
        # Check the query execution status
        query_status = client.get_query_execution(QueryExecutionId=query_execution_id)
        query_execution_status = query_status['QueryExecution']['Status']['State']

        if query_execution_status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
            break

        time.sleep(10)  # Time to wait between checks

    if query_execution_status == 'SUCCEEDED':
        results = []
        # Fetch results
        result_data = client.get_query_results(QueryExecutionId=query_execution_id)
        column_names = [col['Name'] for col in result_data['ResultSet']['ResultSetMetadata']['ColumnInfo']]

        for row in result_data['ResultSet']['Rows'][1:]:  # Skip the header row
            values = [field.get('VarCharValue', None) for field in row['Data']]
            results.append(dict(zip(column_names, values)))

        df = pd.DataFrame(results)
        return df
    else:
        # Handle failures/cancellations and possibly raise an exception based on your project's requirements
        print(f"Query failed: {query_status['QueryExecution']['Status']['StateChangeReason']}")
        return None  # Or raise an appropriate exception

# Calculate the number of days delayed
def calculate_days_delayed(date_of_filing, return_period, frequency):
    filing_date = datetime.strptime(date_of_filing, '%d-%m-%Y')

    if frequency == "Quarterly":
        # Extract the month and year from the return period (ret_prd)
        return_period_month = int(return_period[0:2])
        return_period_year = int(return_period[2:6])

        # Calculate the end of the quarter based on the return period
        if 1 <= return_period_month <= 3:  # Q1 (January to March)
            end_of_quarter = datetime(return_period_year, 3, 31)
        elif 4 <= return_period_month <= 6:  # Q2 (April to June)
            end_of_quarter = datetime(return_period_year, 6, 30)
        elif 7 <= return_period_month <= 9:  # Q3 (July to September)
            end_of_quarter = datetime(return_period_year, 9, 30)
        elif 10 <= return_period_month <= 12:  # Q4 (October to December)
            end_of_quarter = datetime(return_period_year, 12, 31)
        else:
            return None  # Invalid return period

        # Calculate the number of days delayed based on the end of the quarter
        days_delayed = (filing_date - end_of_quarter).days
    elif frequency == "Monthly":
        # In the case of monthly frequency, the return period is the end of the month
        return_period_date = datetime.strptime(return_period, '%m%Y')
        end_of_month = return_period_date + timedelta(days=31)  # Assuming 31 days in a month
        days_delayed = (filing_date - end_of_month).days
    else:
        return None  # Invalid frequency

    return days_delayed

# Calculate the compliance score based on days delayed for monthly frequency
def calculate_monthly_score(days_delayed):
    if days_delayed <= 30:
        return 10.0
    elif 31 <= days_delayed <= 60:
        return 7.0
    elif 61 <= days_delayed <= 90:
        return 4.0
    elif days_delayed >= 91:
        return 2.0
    return 0.0

# Calculate the compliance score based on days delayed for quarterly frequency
def calculate_quarterly_score(days_delayed, return_period):
    # Extract the month and year from the return period (ret_prd)
    return_period_month = int(return_period[0:2])
    return_period_year = int(return_period[2:6])

    if 1 <= return_period_month <= 3:  # Q1 (January to March)
        if days_delayed <= 30:
            return 10.0
        elif 31 <= days_delayed <= 60:
            return 7.0
        elif 61 <= days_delayed <= 90:
            return 4.0
        else:
            return 2.0
    elif 4 <= return_period_month <= 6:  # Q2 (April to June)
        if days_delayed <= 30:
            return 10.0
        elif 31 <= days_delayed <= 60:
            return 7.0
        elif 61 <= days_delayed <= 90:
            return 4.0
        else:
            return 2.0
    elif 7 <= return_period_month <= 9:  # Q3 (July to September)
        if days_delayed <= 31:
            return 10.0
        elif 32 <= days_delayed <= 61:
            return 7.0
        elif 62 <= days_delayed <= 92:
            return 4.0
        else:
            return 2.0
    elif 10 <= return_period_month <= 12:  # Q4 (October to December)
        if days_delayed <= 31:
            return 10.0
        elif 32 <= days_delayed <= 61:
            return 7.0
        elif 62 <= days_delayed <= 92:
            return 4.0
        else:
            return 2.0
    else:
        return 0.0
    
# Generate compliance recommendations based on the aggregated score
def generate_recommendations(aggregated_score):
    if 9.0 <= aggregated_score <= 10.0:
        return "Excellent compliance!"
    elif 7.0 <= aggregated_score < 9.0:
        return "Good compliance, but room for improvement."
    elif 4.0 <= aggregated_score < 7.0:
        return "Moderate compliance, should improve."
    elif 2.0 <= aggregated_score < 4.0:
        return "Low compliance, urgent action needed."
    else:
        return "Very low compliance, immediate action required."
    
def calculate_aggregated_score(scores):
    if not scores:
        return 0.0
    return sum(scores) / len(scores)

def get_data_from_athena(gstin):
    # Run Athena query to get data
    query = f"SELECT * FROM v_gst_returns WHERE ptgstin = '{gstin}'"
    result_df = run_athena_query('gst_data', query)

    # Check if result_df is a DataFrame and not None
    if result_df is not None and not result_df.empty:
        # Perform your data processing steps
        result_df = result_df.sort_values(by=['rtntype', 'ret_prd', 'dof'], ascending=[False, False, False])
        result_df = result_df.drop_duplicates(subset=['rtntype', 'ret_prd'], keep='first')
        return result_df
    else:
        # Log the error or handle it accordingly
        print(f"No data found for GSTIN: {gstin} or failed to retrieve data.")
        # Return an empty DataFrame to maintain consistency
        return pd.DataFrame()

def analyze_dof_frequency(result_df):
    if result_df is not None:
        if result_df.empty:
            return jsonify({"error": "No data found for the provided GSTIN."})

        # Filter data for the last 3 fiscal years
        last_3_fys = result_df['fy'].unique()[-3:]
        last_3_fy_data = result_df[result_df['fy'].isin(last_3_fys)]

        # Create a dictionary to store the analysis results for each return type
        analysis_results = {}

        # Iterate through return types (GSTR1 and GSTR3B)
        for rtntype in ['GSTR1', 'GSTR3B']:
            rtntype_data = last_3_fy_data[last_3_fy_data['rtntype'] == rtntype]

            if not rtntype_data.empty:
                # Create a list to store the frequencies for each fiscal year
                fiscal_year_frequencies = []

                # Iterate through fiscal years
                for fiscal_year in last_3_fys:
                    fy_data = rtntype_data[rtntype_data['fy'] == fiscal_year]

                    # Count the occurrence of each DOF within the fiscal year
                    dof_counts = Counter(fy_data['dof'])

                    # Determine the most common DOF for this fiscal year
                    # print(dof_counts.most_common)
                    if dof_counts:
                        most_common_dof = dof_counts.most_common(1)[0][0]

                        # Check if the most common DOF occurs 3 times (quarterly) or more frequently
                        if dof_counts[most_common_dof] >= 3:
                            fiscal_year_frequencies.append("Quarterly")
                        else:
                            fiscal_year_frequencies.append("Monthly")

                # Determine the most common frequency across all fiscal years for this return type
                common_frequency = max(set(fiscal_year_frequencies), key=fiscal_year_frequencies.count)
                analysis_results[rtntype] = common_frequency
            else:
                analysis_results[rtntype] = "No data found"


        return analysis_results
    else:
        return None

def get_recommendation_api(frequencies, database_data, gstin):
    if frequencies is None:
        return jsonify({"error": "Frequency data not available for the provided GSTIN. Run /analyze_dof_frequency first."})

    fiscal_years = set()
    for entry in database_data['fy']:
        fiscal_years.add(entry)

    # Define an empty list to store the response data
    response = []
    all_individual_scores = []  # Initialize the list for individual scores

    # Create dictionaries to store aggregated scores for each return type
    return_type_scores = {return_type: [] for return_type in ["GSTR1", "GSTR3B"]}

    for fiscal_year_entry in fiscal_years:
        for return_type in ["GSTR1", "GSTR3B"]:  # Default return types
            scores = []
            individual_scores = []

            found = False

            for idx, row in database_data.iterrows():
                if (
                    row['valid'] == 'Y'
                    and row['rtntype'] == return_type
                    and row['fy'] == fiscal_year_entry
                ):
                    days_delayed = calculate_days_delayed(row['dof'], row['ret_prd'], frequencies.get(return_type))
                    # Get the frequency for the current return type
                    return_type_frequency = frequencies.get(return_type, "Unknown")

                    # Calculate compliance score based on the return type's frequency
                    if return_type_frequency == "Monthly":
                        score = calculate_monthly_score(days_delayed)
                    elif return_type_frequency == "Quarterly":
                        score = calculate_quarterly_score(days_delayed, row['ret_prd'])
                    else:
                        score = 0.0  # Default to 0.0 for unknown frequency

                    scores.append(score)
                    found = True
            recommendations = ""
            if found:
                aggregate_score = calculate_aggregated_score(scores)
                recommendations = generate_recommendations(aggregate_score)

                # Update the return_type_scores dictionary with the aggregate score for this return type
                if return_type in return_type_scores:
                    return_type_scores[return_type].append(aggregate_score)

                return_data = {
                    "gstin": gstin,
                    "fiscal_year": fiscal_year_entry,
                    "return_type": return_type,
                    "aggregated_score": aggregate_score,
                    "recommendations": recommendations
                }
                response.append(return_data)
            else:
                # Return custom recommendation for missing return type
                custom_recommendation = "Return type not found for this fiscal year."
                error_data = {
                    "gstin": gstin,
                    "fiscal_year": fiscal_year_entry,
                    "return_type": return_type,
                    "aggregated_score": 0.0,  # Set the score to 0 for missing return types
                    "recommendations": custom_recommendation
                }
                response.append(error_data)

     # Calculate the final aggregated score for all individual scores
    final_aggregated_score = calculate_aggregated_score(all_individual_scores)
    
    # Calculate the average aggregated score for GSTR1 and GSTR3B
    gstr1_average_score = calculate_aggregated_score(return_type_scores["GSTR1"])
    gstr3b_average_score = calculate_aggregated_score(return_type_scores["GSTR3B"])
    final_aggregated_score = (gstr1_average_score + gstr3b_average_score) / 2.0
    final_recommendations = generate_recommendations(final_aggregated_score)
    # final_compliance_score = {
    #     "Aggregated Score": final_aggregated_score,
    #     "GSTR1": gstr1_average_score,
    #     "GSTR3B": gstr3b_average_score,
    #     "fiscal_year": "All Fiscal Years",
    #     "recommendations": final_recommendations
        
    # }
    final_compliance_score=final_aggregated_score

    response_data = {
        "Final Compliance Score": final_compliance_score
    }

    global final_compliance_score_data
    final_compliance_score_data = final_compliance_score  # Store the data in the global variable
    return final_compliance_score

def process_gstin(gstin):
    """Process data for a single GSTIN."""
    # Fetch data from Athena
    results = get_data_from_athena(gstin)
    if results.empty:
        return None

    # Analyze the frequency of filing
    analysis = analyze_dof_frequency(results)
    if analysis is None:
        return None

    # Generate recommendations based on the analysis
    recommendations = get_recommendation_api(analysis, results, gstin)
    return recommendations

# @app.route('/Final_Compliance_Scores', methods=['POST'])
def get_final_compliance_scores():
    data = request.json
    borrower_gst = data.get('borrower_gst')
    trader_gst = data.get('trader_gst')
    

    # Validation
    if not borrower_gst or not trader_gst:
        return jsonify({'error': 'Both borrower_gst and trader_gst are required.'})

    # Process the GSTINs and store the results
    borrower_results = process_gstin(borrower_gst)  # this should be a regular dictionary or value
    trader_results = process_gstin(trader_gst)  # this should be a regular dictionary or value

    # Now, you can use jsonify since you're in the main route function
    return jsonify({
        'borrower_gst': borrower_results,  # these are regular dictionaries or values
        'trader_gst': trader_results
    })
   
def calculate_vintage_score(operational_vintage):
    if operational_vintage <= 24:
        vintage_score = (operational_vintage / 24) * 25  # Score between 0-25 for 0-24 months
    elif operational_vintage <= 48:
        vintage_score = 25 + ((operational_vintage - 24) / (48 - 24)) * 25  # Score between 25-50 for 25-48 months
    elif operational_vintage <= 72:
        vintage_score = 50 + ((operational_vintage - 48) / (72 - 48)) * 25  # Score between 50-75 for 49-72 months
    else:
        vintage_score = 100  # Score between 75-100 for 73+ months

    return max(0, min(vintage_score, 100))  # Ensure the score is between 0 and 100

def calculate_recency_score(recency_invoice, recency_weights):
    # Validate inputs
    if not recency_invoice or not recency_weights:
        raise ValueError("Recency data or weights are missing")

    if not all(isinstance(score, (int, float)) for score in recency_invoice.values()):
        raise ValueError("All invoice scores should be numeric")

    if not all(isinstance(weight, (int, float)) for weight in recency_weights.values()):
        raise ValueError("All weights should be numeric")

    if abs(sum(recency_weights.values()) - 1.0) > 0.01:  # Allowing a small arithmetic tolerance
        raise ValueError("All weights should sum up to 1.0")

    # Calculate the weighted average
    weighted_scores = [recency_invoice[period] * recency_weights[period] for period in recency_invoice]
    recency_score = sum(weighted_scores)

    return recency_score

def detect_and_handle_outliers(df, column):
    # Check if the column is numeric
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise ValueError(f"The column '{column}' is not numeric. Please ensure the data is numeric before detecting outliers.")
    
    # Calculate the quartiles
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1

    # Define bounds
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR

    # Identify outliers
    outliers = df[(df[column] < lower_bound) | (df[column] > upper_bound)]
    # If there are any outliers, replace them with the mean of the non-outliers
    if not outliers.empty:
        original_mean = df[column].mean()
        print("original mean",original_mean)
        non_outliers_mean = df[(df[column] >= lower_bound) & (df[column] <= upper_bound)][column].mean()
        print("non_outliers_mean",non_outliers_mean)

        df.loc[(df[column] < lower_bound) | (df[column] > upper_bound), column] = non_outliers_mean

    return df

# Display the modified function
detect_and_handle_outliers
  
def calculate_recency_invoice_tally(borrower_gst, trader_gst):
    # SQL query
    query = f"""
     WITH MonthlyData AS (
    SELECT
        ptgstin,
        ctin,
        EXTRACT(year FROM "DATE") AS year,
        EXTRACT(month FROM "DATE") AS month,
        COUNT(*) AS num_invoices
    FROM "prod-erp".v_rpt_tally
    WHERE ptgstin = '{borrower_gst}' AND inv_typ='Sales'
    GROUP BY ptgstin, ctin, EXTRACT(year FROM "DATE"), EXTRACT(month FROM "DATE")
    ),

    MaxMonth AS (
        SELECT
            ptgstin,
           
            MAX(EXTRACT(year FROM "DATE") * 12 + EXTRACT(month FROM "DATE")) AS max_month
        FROM "prod-erp".v_rpt_tally
        WHERE ptgstin = '{borrower_gst}' 
        GROUP BY ptgstin
    )

    SELECT
        MD.ptgstin,
        MD.ctin,
        SUM(CASE WHEN MM.max_month - (MD.year * 12 + MD.month) BETWEEN 0 AND 2 THEN MD.num_invoices ELSE 0 END) AS "1_3_months",
        SUM(CASE WHEN MM.max_month - (MD.year * 12 + MD.month) BETWEEN 3 AND 5 THEN MD.num_invoices ELSE 0 END) AS "2_3_months",
        SUM(CASE WHEN MM.max_month - (MD.year * 12 + MD.month) BETWEEN 6 AND 8 THEN MD.num_invoices ELSE 0 END) AS "3_3_months",
        SUM(CASE WHEN MM.max_month - (MD.year * 12 + MD.month) BETWEEN 9 AND 11 THEN MD.num_invoices ELSE 0 END) AS "4_3_months"
    FROM MonthlyData MD
    JOIN MaxMonth MM ON MD.ptgstin = MM.ptgstin
    where MD.ctin='{trader_gst}'
    GROUP BY MD.ptgstin, MD.ctin
    ORDER BY MD.ptgstin, MD.ctin;
    """

    # Execute the query and get the results in a DataFrame.
    result_df = run_athena_query('prod-erp', query)

    # Prepare a default structure for recency_invoice_dict with all values as 0.
    recency_invoice_dict = {
        "1_3_months": 0,
        "2_3_months": 0,
        "3_3_months": 0,
        "4_3_months": 0
    }

    # If the query returns a result, then we proceed with extracting required values.
    if not result_df.empty:
        # We are interested in specific columns, so we try extracting values from them.
        for column in recency_invoice_dict.keys():
            if column in result_df.columns:
                try:
                    value = int(result_df[column].iloc[0])
                    recency_invoice_dict[column] = value
                except (ValueError, TypeError):
                    print(f"Warning: Cannot convert value in '{column}' to an integer. Using default value 0.")

    # Output the dictionary
    print(recency_invoice_dict)
    return recency_invoice_dict



def calculate_average_invoice_tally(borrower_gst, trader_gst):
    query = f"""
    SELECT ptgstin, ctin, COUNT(id) AS NumberOfInvoices,
       SUM(CAST(val AS double)) AS TotalInvoiceAmount,
       AVG(CAST(val AS double)) AS AvgInvoiceAmount
    FROM "prod-erp".v_rpt_tally
    WHERE ptgstin = '{borrower_gst}' AND ctin = '{trader_gst}' AND (LOWER(inv_typ) LIKE 'sales%')
    AND (
        (YEAR(date) * 12 + MONTH(date)) >= ((YEAR(CURRENT_DATE) - 1) * 12 + MONTH(CURRENT_DATE))
    )
    GROUP BY ptgstin, ctin;
    """

    result = run_athena_query('prod-erp', query)

    # Check if 'AvgInvoiceAmount' is in the DataFrame
    if 'AvgInvoiceAmount' in result:
        # Extract the first value from the Series
        average_invoice_amount = result['AvgInvoiceAmount'].iloc[0]
    else:
        # Handle the absence of 'AvgInvoiceAmount'
        print("AvgInvoiceAmount not found in the result.")
        average_invoice_amount = None

    return average_invoice_amount


    
def calculate_invoice_frequency_tally(borrower_gst, trader_gst):
  
    query = f"""
    WITH MaxMonth AS (
    SELECT
        MAX(EXTRACT(year FROM "DATE") * 100 + EXTRACT(month FROM "DATE")) AS max_month
    FROM "prod-erp".v_rpt_tally
        
    WHERE
        ptgstin = '{borrower_gst}' -- Replace with your specific pgstin
)

SELECT
    ptgstin,
    ctin,
    COUNT(DISTINCT inv_no) AS "Number of Invoices",
    12 AS "Number of Months",
    (COUNT(DISTINCT inv_no) * 1.0) / 12 AS "Frequency"
FROM
    "prod-erp".v_rpt_tally
CROSS JOIN
    MaxMonth
WHERE
    ptgstin = '{borrower_gst}' -- Replace with your specific pgstin
    AND ctin = '{trader_gst}' -- Replace with your specific ctin
    AND inv_typ='Sales'
    AND (EXTRACT(year FROM "DATE") * 100 + EXTRACT(month FROM "DATE")) > (SELECT max_month FROM MaxMonth) - 100
    AND (EXTRACT(year FROM "DATE") * 100 + EXTRACT(month FROM "DATE")) <= (SELECT max_month FROM MaxMonth)
GROUP BY
    ptgstin, ctin;
    """
    result = run_athena_query('prod-erp',query)

    try:
        # Extract the first value from the 'Frequency' column.
        # If the column contains more than one row, you might need additional logic to determine which row's data to use.
        number_of_invoices = result['Number of Invoices'].iloc[0]

        # Convert to int to ensure that the value is numeric.
        # This will raise a ValueError if the conversion fails.
        number_of_invoices = int(number_of_invoices)
        
    except IndexError:
        # Handle the case where the 'Frequency' column is empty.
        print("Error: 'Number of Invoices' is not a number.")
        number_of_invoices = 0.0  # Use an appropriate default value.

    except ValueError:
        # Handle the case where conversion to int fails.
        print("Error: 'Number of Invoices' is not a number.")
        number_of_invoices = 0.0
    except KeyError:
        # Handle the case where the 'Frequency' column does not exist.
        print("Error: 'Number of Invoices' column is missing in the result set.")
        number_of_invoices = 0.0  # Use an appropriate default value.

    # Return the number of invoices as a single numeric value.
    print("Number of Invoices:", number_of_invoices)
    return number_of_invoices
    # invoice_frequency = result['Frequency']  # Adjust based on actual result structure
    # return invoice_frequency

def calculate_recency_invoice(borrower_gst, trader_gst):
    # SQL query for recency of invoices.
    query = f"""
    WITH MonthlyData AS (
        SELECT
            ptgstin,
            ctin,
            year,
            month,
            COUNT(DISTINCT(inum)) AS num_invoices
        FROM gst_data.v_gstr1b2b
        WHERE ptgstin = '{borrower_gst}' 
        GROUP BY ptgstin, ctin, year, month
    ),
    MaxMonth AS (
        SELECT
            ptgstin,
            MAX(year * 12 + month) AS max_month
        FROM MonthlyData
        GROUP BY ptgstin
    )
    SELECT
        MD.ptgstin,
        MD.ctin,
        SUM(CASE WHEN max_month - (MD.year * 12 + MD.month) BETWEEN 0 AND 2 THEN MD.num_invoices ELSE 0 END) AS "1_3_months",
        SUM(CASE WHEN max_month - (MD.year * 12 + MD.month) BETWEEN 3 AND 5 THEN MD.num_invoices ELSE 0 END) AS "2_3_months",
        SUM(CASE WHEN max_month - (MD.year * 12 + MD.month) BETWEEN 6 AND 8 THEN MD.num_invoices ELSE 0 END) AS "3_3_months",
        SUM(CASE WHEN max_month - (MD.year * 12 + MD.month) BETWEEN 9 AND 11 THEN MD.num_invoices ELSE 0 END) AS "4_3_months"
    FROM MonthlyData MD
    JOIN MaxMonth MM ON MD.ptgstin = MM.ptgstin 
    WHERE ctin='{trader_gst}'
    GROUP BY MD.ptgstin, MD.ctin
    ORDER BY MD.ptgstin, MD.ctin;
    """

    # Execute the query and get the results in a DataFrame.
    # Please replace 'run_athena_query' with your actual function that executes the SQL query.
    result_df = run_athena_query('gst_data',query)  # This function should run your query and return a DataFrame.

    # Prepare a default structure for recency_invoice_dict with all values as 0.
    recency_invoice_dict = {
        "1_3_months": 0,
        "2_3_months": 0,
        "3_3_months": 0,
        "4_3_months": 0
    }

    # If the query returns a result, then we proceed with extracting required values.
    if not result_df.empty:
        # We are interested in specific columns, so we try extracting values from them.
        # If the column doesn't exist or value is not an integer, it remains the default 0.
        for column in recency_invoice_dict.keys():
            if column in result_df.columns:
                # Try converting the value to an integer.
                try:
                    # We are using `.iloc[0]` assuming we want the first row entry of each column.
                    value = int(result_df[column].iloc[0])
                    recency_invoice_dict[column] = value
                except (ValueError, TypeError):
                    print(f"Warning: Cannot convert value in '{column}' to an integer. Using default value 0.")
                    # If conversion fails, the value remains 0 as per the default dict.

    # By this point, recency_invoice_dict is either filled with actual values or contains default 0s.
    # print(recency_invoice_dict)
    return recency_invoice_dict

def calculate_average_invoice_amount(borrower_gst, trader_gst):
    query = f"""
    SELECT
        ptgstin,
        ctin,
        COALESCE(SUM(txval), 0) + COALESCE(SUM(iamt), 0) + COALESCE(SUM(camt), 0) + COALESCE(SUM(samt), 0) + COALESCE(SUM(csamt), 0) AS TotalInvoiceAmount,
        COUNT(DISTINCT(inum)) AS NumberOfInvoices,
        CASE
            WHEN COUNT(*) > 0 THEN (COALESCE(SUM(txval), 0) + COALESCE(SUM(iamt), 0) + COALESCE(SUM(camt), 0) + COALESCE(SUM(samt), 0) + COALESCE(SUM(csamt), 0)) / COUNT(DISTINCT(inum))
            ELSE NULL
        END AS AvgInvoiceAmount
    FROM
        v_gstr1b2b
    WHERE
        (Year * 12 + Month) >= ((YEAR(current_date) - 1) * 12 + MONTH(current_date))
        AND ptgstin = '{borrower_gst}' 
        AND ctin = '{trader_gst}'   
    GROUP BY
        ptgstin, ctin;
    """
    result = run_athena_query('gst_data',query)
    # Process the 'result' as per your existing logic to extract the average invoice amount
    # and then return the relevant value.
    # For example:
    # Assuming result['AvgInvoiceAmount'] is your Series after running the query
    # After extracting the value from the DataFrame
    average_invoice_amount = float(result['AvgInvoiceAmount'].iloc[0]) if not result.empty else 0.0

    print(type(average_invoice_amount))
    print(average_invoice_amount)

  # Adjust based on actual result structure
    return average_invoice_amount

def calculate_invoice_frequency(borrower_gst, trader_gst):
    query = f"""
    WITH MaxMonth AS (
    SELECT
        MAX(CAST(year AS INT) * 100 + CAST(month AS INT)) AS max_month
    FROM
        gst_data.v_gstr1b2b
    WHERE
        ptgstin = '{borrower_gst}' -- Replace with your specific pgstin
)

SELECT
    ptgstin,
    ctin,
    COUNT(DISTINCT inum) AS "Number of Invoices",
    12 AS "Number of Months",
    (COUNT(DISTINCT inum) * 1.0) / 12 AS "Frequency"
FROM
    gst_data.v_gstr1b2b
CROSS JOIN
    MaxMonth
WHERE
    ptgstin = '{borrower_gst}' -- Replace with your specific pgstin
    AND ctin = '{trader_gst}' -- Replace with your specific ctin
    AND (CAST(year AS INT) * 100 + CAST(month AS INT)) > (SELECT max_month FROM MaxMonth) - 100
    AND (CAST(year AS INT) * 100 + CAST(month AS INT)) <= (SELECT max_month FROM MaxMonth)
GROUP BY
    ptgstin, ctin;
    """
    result = run_athena_query('gst_data',query)

    try:
        # Extract the first value from the 'Frequency' column.
        # If the column contains more than one row, you might need additional logic to determine which row's data to use.
        number_of_invoices = result['Number of Invoices'].iloc[0]

        # Convert to int to ensure that the value is numeric.
        # This will raise a ValueError if the conversion fails.
        number_of_invoices = int(number_of_invoices)
        
    except IndexError:
        # Handle the case where the 'Frequency' column is empty.
        print("Error: 'Number of Invoices' is not a number.")
        number_of_invoices = 0.0  # Use an appropriate default value.

    except ValueError:
        # Handle the case where conversion to int fails.
        print("Error: 'Number of Invoices' is not a number.")
        number_of_invoices = 0.0
    except KeyError:
        # Handle the case where the 'Frequency' column does not exist.
        print("Error: 'Number of Invoices' column is missing in the result set.")
        number_of_invoices = 0.0  # Use an appropriate default value.

    # Return the number of invoices as a single numeric value.
    print("Number of Invoices:", number_of_invoices)
    return number_of_invoices
    # invoice_frequency = result['Frequency']  # Adjust based on actual result structure
    # return invoice_frequency

def get_operational_vintage(trader_gst):
    # Define the SQL query
    query = f"""
        SELECT ptgstin, COUNT(DISTINCT ret_prd) AS OpVin
        FROM gst_data.v_gst_returns
        WHERE rtntype = 'GSTR1'
          AND ptgstin = '{trader_gst}'
        GROUP BY ptgstin;
    """
        # Execute the query and get the result
    result_df = run_athena_query('gst_data',query)

    # Now, we need to make sure we extract the operational vintage as an integer.
    if not result_df.empty and 'OpVin' in result_df.columns:
        operational_vintage = result_df['OpVin'].iloc[0]
        if isinstance(operational_vintage, str):
            # If for some reason the value is a string, we convert it to integer
            operational_vintage = int(operational_vintage)
    else:
        print("No operational vintage data available.")
        operational_vintage = 0  # or any other default value

    return operational_vintage
    
    # In case there's no data or an unexpected data type, return a default value or handle the error as appropriate
    # return None  # or some default value, or raise an error


def calculate_invoice_to_cash_flow_tally(borrower_gst):
    # Define your query to retrieve data
    query = f"""
    SELECT 
    
    EXTRACT(YEAR FROM date) AS Year,
    EXTRACT(MONTH FROM date) AS Month,
    ROUND(COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Sales', 'Receipt', 'Credit Note') THEN val ELSE 0 END)), 0), 3) AS Inflow,
    ROUND(COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Purchase', 'Payment', 'Debit Note') THEN val ELSE 0 END)), 0), 3) AS Outflow,
    ROUND(COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Sales', 'Receipt', 'Credit Note') THEN val ELSE 0 END)), 0) -
         COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Purchase', 'Payment', 'Debit Note') THEN val ELSE 0 END)), 0), 3) AS CashFlow,
    ROUND(ABS(SUM(CASE WHEN inv_typ = 'Sales' THEN val ELSE 0 END)), 3) AS Total_Invoice_Value,
    CASE
        WHEN ROUND(COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Sales', 'Receipt', 'Credit Note') THEN val ELSE 0 END)), 0) -
             COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Purchase', 'Payment', 'Debit Note') THEN val ELSE 0 END)), 0), 3) != 0
        THEN ROUND(ABS(SUM(CASE WHEN inv_typ = 'Sales' THEN val ELSE 0 END)) /
             (COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Sales', 'Receipt', 'Credit Note') THEN val ELSE 0 END)), 0) -
             COALESCE(SUM(ABS(CASE WHEN inv_typ IN ('Purchase', 'Payment', 'Debit Note') THEN val ELSE 0 END)), 0)), 3)
        ELSE 0
    END AS Invoice_CashFlow_Ratio
FROM 
    "prod-erp".v_rpt_tally
    WHERE ptgstin ='{borrower_gst}'
GROUP BY 
    EXTRACT(YEAR FROM date),
    EXTRACT(MONTH FROM date)
ORDER BY 
    Year, Month;
    """
    
    # Assuming run_athena_query or similar function exists and returns a DataFrame
    data = run_athena_query('prod-erp',query)  # This line needs to be defined based on how you fetch data
    if data.empty:
        print("No data fetched from the database.")
        return
    # Data manipulation operations
    data['Year'] = pd.to_numeric(data['Year'], errors='coerce')
    data['Month'] = pd.to_numeric(data['Month'], errors='coerce')
    data['Invoice_CashFlow_Ratio'] = pd.to_numeric(data['Invoice_CashFlow_Ratio'], errors='coerce')

    # Create a Date column from Year and Month for easier handling and sorting
    data['Date'] = pd.to_datetime(data[['Year', 'Month']].assign(DAY=1))
    
    # Sort the DataFrame based on Date
    data.sort_values('Date', inplace=True)
    
    # Set Date as the index for time series analysis
    data.set_index('Date', inplace=True)

    # Assuming 'detect_and_handle_outliers' is another function that modifies the DataFrame
    data = detect_and_handle_outliers(data, 'Invoice_CashFlow_Ratio')

    # Calculate the EMA with a span of 3 for Invoice_CashFlow_Ratio
    data['EMA'] = data['Invoice_CashFlow_Ratio'].ewm(span=3, adjust=False).mean()

    # Retrieve the most recent EMA value
    recent_ema = data['EMA'].iloc[-1]
    print("Invoice to cashflow tally:", recent_ema)
    return recent_ema



def calculate_invoice_to_cash_flow(borrower_gst):
    # Define your query to retrieve data
    query = f"""
    WITH DateRange AS (
    SELECT 
        MAX(year_month) AS max_date,
        DATE_ADD('month', -12, MAX(year_month)) AS start_date
    FROM gst_data.v_gst_cashflow 
    where v_gst_cashflow.ptgstin ='{borrower_gst}'
    )
    SELECT yt.ptgstin, yt.year_month, yt.invoice_to_cashflow 
    FROM gst_data.v_gst_cashflow yt
    JOIN DateRange dr
    ON yt.year_month BETWEEN dr.start_date AND dr.max_date
    where yt.ptgstin ='{borrower_gst}'
    """

    # Execute the query through your specific database connection
    data = run_athena_query('gst_data', query)  # Placeholder for actual query execution

    if data is None or data.empty:
        raise Exception('Data retrieval failed or data is empty')

    # Ensure proper column names after the query
    data.rename(columns={'year_month': 'date', 'invoice_to_cashflow': 'Invoice_to_CashFlow'}, inplace=True)

    # Convert 'date' from string to actual date type and sort the DataFrame based on date
    data['date'] = pd.to_datetime(data['date'])
    data.sort_values('date', inplace=True)

    # Convert the 'Invoice_to_CashFlow' column to a numeric type, coercing errors if any non-convertible data is present
    data['Invoice_to_CashFlow'] = pd.to_numeric(data['Invoice_to_CashFlow'], errors='coerce')

    # Detect and handle outliers
    data = detect_and_handle_outliers(data, 'Invoice_to_CashFlow')

    # Recalculate the mean excluding outliers for reporting purposes (optional)
    adjusted_mean = data['Invoice_to_CashFlow'].mean()

    # Calculate the EMA with a span of 3 (this can be adjusted as needed)
    data['EMA'] = data['Invoice_to_CashFlow'].ewm(span=3, adjust=False).mean()

    # Retrieve the most recent EMA value
    recent_ema = data['EMA'].iloc[-1]

    # Print the adjusted mean and most recent EMA for debugging
    print("Adjusted mean:", adjusted_mean)
    print("Recent EMA:", recent_ema)

    return recent_ema


def fetch_gst_data(borrower_gst, trader_gst):
    query = f"""
    SELECT subquery.ptgstin, subquery.ctin, subquery.inv_no, val, txval, subquery.inv_date
FROM (
    SELECT ptgstin, ctin, inum AS inv_no,date_parse(idt, '%d-%m-%Y') as inv_date,val,txval
    FROM "gst_data"."v_gstr1b2b"
) as subquery
WHERE subquery.ptgstin = '{borrower_gst}' 
  AND subquery.ctin = '{trader_gst}';
    """
    result = run_athena_query('gst_data',query)
    return result

def fetch_tally_data(borrower_gst, trader_gst):
    query = f"""
    SELECT 
    ptgstin, 
    ctin, 
    inv_no, 
    ABS(CAST(val AS double)) as val, 
    ABS(CAST(taxval AS double)) as taxval, 
    "DATE" as inv_date
FROM "prod-erp"."v_rpt_tally"
WHERE 
    ptgstin = '{borrower_gst}' 
    AND ctin = '{trader_gst}'
    AND inv_typ='Sales';
 
    """
    result = run_athena_query('prod-erp',query)
    return result


def compare_data(borrower_gst, trader_gst):
    percentage_difference = 0  # Default to 0 or another sensible default for your application
    filtered_gst_data = None
    filtered_tally_data = None
    compare_result_message = ""
    try:
        gst_data = fetch_gst_data(borrower_gst, trader_gst)
        tally_data = fetch_tally_data(borrower_gst, trader_gst)

        if gst_data.empty or tally_data.empty:
            empty_dataset = 'GST' if gst_data.empty else 'Tally'
            if gst_data.empty and tally_data.empty:
                empty_dataset = 'GST and Tally'
            return {
                "error": True,
                "message": f"No data present in {empty_dataset} dataset(s)."
            }

        # Convert inv_date to datetime
        gst_data['inv_date'] = pd.to_datetime(gst_data['inv_date'])
        tally_data['inv_date'] = pd.to_datetime(tally_data['inv_date'])

        # Determine the date range for comparison
        max_inv_date_gst = gst_data['inv_date'].max()
        max_inv_date_tally = tally_data['inv_date'].max()
        comparison_start_date = min(max_inv_date_gst, max_inv_date_tally)
        comparison_end_date = comparison_start_date - timedelta(days=90)
        # Create copies of the filtered data to avoid SettingWithCopyWarning
        filtered_gst_data = gst_data[(gst_data['inv_date'] <= comparison_start_date) & 
                                     (gst_data['inv_date'] > comparison_end_date)].copy()
        filtered_tally_data = tally_data[(tally_data['inv_date'] <= comparison_start_date) & 
                                         (tally_data['inv_date'] > comparison_end_date)].copy()

        # Convert 'taxval' to numeric in both DataFrames
        filtered_gst_data['val'] = pd.to_numeric(filtered_gst_data['val'], errors='coerce')
        filtered_tally_data['val'] = pd.to_numeric(filtered_tally_data['val'], errors='coerce')


        # Remove duplicates from GST data based on inv_no
        filtered_gst_data = filtered_gst_data.drop_duplicates(subset=['inv_no'])
        filtered_gst_data.sort_values(by='inv_date', inplace=True)
        filtered_tally_data=filtered_tally_data.drop_duplicates(subset=['inv_date'])
        filtered_tally_data.sort_values(by='inv_date', inplace=True)
        print("gst data ",filtered_gst_data)
        print("tally data " , filtered_tally_data)
        # Initialize variables to track total taxval and total difference
        # Iterate through the dates and calculate differences
        total_difference = 0
        total_taxval = 0
        for date in pd.date_range(start=comparison_end_date, end=comparison_start_date):
            if date in filtered_gst_data['inv_date'].values and date in filtered_tally_data['inv_date'].values:
                daily_sum_gst = filtered_gst_data[filtered_gst_data['inv_date'] == date]['val'].sum()
                daily_sum_tally = filtered_tally_data[filtered_tally_data['inv_date'] == date]['val'].sum()

                total_difference += abs(daily_sum_gst - daily_sum_tally)
                total_taxval += daily_sum_gst + daily_sum_tally

        # Calculate percentage difference
        if total_taxval > 0:
            percentage_difference = (total_difference / total_taxval) * 100
            print("% ",percentage_difference)
        else:
            return "No taxval data available for comparison."
        # Construct the return data
        data_to_return = {
            "percentage_difference": percentage_difference,
            "filtered_gst_data": filtered_gst_data.to_dict('records'),  # Convert DataFrame to list of dicts
            "filtered_tally_data": filtered_tally_data.to_dict('records'),  # Convert DataFrame to list of dicts
            "result_message": ""
        }
        # Check if percentage difference is within the threshold
        if percentage_difference <= 5:
            data_to_return["result_message"] = "Data comparison within threshold. Proceed with calculation."
        else:
            data_to_return["result_message"] = f"Mismatch in data: {percentage_difference}% difference."
        return data_to_return
    except Exception as e:
        return f"Error in data processing: {e}"




def get_most_recent_tally_date(borrower_gst):
    query = f"""
    SELECT MAX(date) AS recent_date
    FROM "prod-erp".v_rpt_tally
    WHERE inv_typ ='Sales' AND ptgstin ='{borrower_gst}';

    """
    result = run_athena_query('prod-erp', query)
    print(result)
    # Extract the first date string from the result DataFrame
    recent_date_str = result['recent_date'].iloc[0] if not result.empty else None
    print(recent_date_str)
    return recent_date_str


def get_most_recent_gst_date(borrower_gst):
    query = f"""
    SELECT MAX(date_parse(idt, '%d-%m-%Y')) AS recent_date
    FROM gst_data.v_gstr1b2b
    WHERE ptgstin ='{borrower_gst}'
    """
    result = run_athena_query('gst_data', query)
    # Extract the first date string from the result DataFrame
    recent_date_str = result['recent_date'].iloc[0] if not result.empty else None
    return recent_date_str



def load_config1(filename):
    with open(filename, 'r') as file:
        return json.load(file)


@app.route('/compute_credit_score', methods=['POST'])
def compute_credit_score_api():
    data = request.json
    invoice_data = data.get('invoice_data',{})
    additional_metrics_input = data.get('additional_metrics', {})
    errors=[]
    # Load configuration files
    combined_config = load_config1('config_weights.json')
    weights = combined_config['base_weights']
    recency_weights = combined_config['recency_weights']
    additional_weights = combined_config['additional_weights']
    overall_weight = combined_config['additional_overall_weight']['overall_weight']
    # Check for empty strings or None values
    
    if not invoice_data.get('borrower_gst'):
        errors.append("Please enter the value for 'Borrower GST'.")

    if not invoice_data.get('trader_gst'):
        errors.append("Please enter the value for 'Trader GST'.")

        # Check if 'current_invoice_amount' is present, not None, and is a number
    if 'current_invoice_amount' not in invoice_data or invoice_data['current_invoice_amount'] is None:
        errors.append("Please provide 'Current Invoice Amount'.")
    else:
        try:
            # Check if it's a valid number (also catches empty strings)
            current_invoice_amount = float(invoice_data['current_invoice_amount'])
            
            # Check if the number is positive
            if current_invoice_amount <= 0:
                errors.append("Please provide a positive value for 'Current Invoice Amount'.")

            # Check if the number is an integer (no decimal part)
            if not current_invoice_amount.is_integer():
                errors.append("The 'Current Invoice Amount' should be a whole number without decimal places.")

        except ValueError:
            errors.append("Please provide a valid number for 'Current Invoice Amount'.")

      # Check if there were any errors and return them
    if errors:
        return jsonify({"errors": errors}), 400
    
    borrower_gst = invoice_data['borrower_gst']
    trader_gst = invoice_data['trader_gst']
    current_invoice_amount = invoice_data['current_invoice_amount']
    
    detailed_insights = []
    transaction_uuid=str(uuid.uuid4())
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    transaction_log_entry = {
        transaction_uuid: {
            "timestamp": timestamp,  # set the timestamp immediately
            
        }
    }
    # Calculate compliance scores
    borrower_compliance_score = process_gstin(borrower_gst)
    trader_compliance_score = process_gstin(trader_gst)
    # Check if data was successfully retrieved
    if borrower_compliance_score is None:
        message = f"No data found or failed to retrieve data for borrower gstin: {borrower_gst}."
        response = {
            "message": message,
            "request_id":transaction_uuid,
            "timestamp":timestamp
        }
        return jsonify(response), 400
    if trader_compliance_score is None:
        message = f"No data found or failed to retrieve data for borrower gstin: {trader_gst}."
        response = {
            "message": message,
            "request_id":transaction_uuid,
            "timestamp":timestamp
        }
        return jsonify(response), 400

       # Prepare a dictionary to store which entity has a low compliance score along with the actual score
 # Check the compliance scores before proceeding
    if borrower_compliance_score < 7 or trader_compliance_score < 7:
        # One of the compliance scores is below 7, return an error message
        print("Either borrower or trader has a low compliance score. Cannot proceed.")

        low_scores = []
        if borrower_compliance_score < 7:
            low_scores.append(f"Borrower : {borrower_compliance_score}")
        if trader_compliance_score < 7:
            low_scores.append(f"Trader : {trader_compliance_score}")
        
        message = "Cannot calculate credit score due to low compliance score of " + ", ".join(low_scores)

        response = {
            "message": message,
            "request_id":transaction_uuid,
            "timestamp":timestamp
        }
        return jsonify(response), 400  # 400 Bad Request or 422 Unprocessable Entity would be suitable here

    else:
         # Assuming borrower_gst is defined
        tally_recent_date_str = get_most_recent_tally_date(borrower_gst)
        gst_recent_date_str = get_most_recent_gst_date(borrower_gst)

        tally_recent_date = datetime.strptime(tally_recent_date_str, '%Y-%m-%d %H:%M:%S.%f') if tally_recent_date_str else None
        gst_recent_date = datetime.strptime(gst_recent_date_str, '%Y-%m-%d %H:%M:%S.%f') if gst_recent_date_str else None

        print("GST Recent Date:", gst_recent_date)
        print("Tally Recent Date:", tally_recent_date)
    
    #     comparison_data = compare_data(borrower_gst, trader_gst)
    #     if "error" in comparison_data:
    # # Handle the error case
    #         print(comparison_data["error"])
        
    #         # Depending on your application logic, you might want to stop further processing here
    #     else:
    #         # Continue processing with the comparison data
    #         percentage_difference = comparison_data["percentage_difference"]
    #         filtered_gst_data = comparison_data["filtered_gst_data"]
    #         filtered_tally_data = comparison_data["filtered_tally_data"]
    #         compare_result_message = comparison_data["result_message"]
    #         print("Data Comparison Result: ", comparison_data["result_message"])
        
            # Determine if Tally data is outdated (> 45 days from the current date)
            # Determine if Tally data is outdated or not present
        current_date = datetime.now()
        tally_outdated_or_missing = tally_recent_date is None or (current_date - tally_recent_date).days > 45 if tally_recent_date else True

        # Adjust the condition to handle NoneType comparison issue
        if gst_recent_date and (tally_recent_date is None or (tally_recent_date and gst_recent_date > tally_recent_date) or tally_outdated_or_missing):
            # Use GST data
            invoice_frequency = calculate_invoice_frequency(borrower_gst, trader_gst)
            print(invoice_frequency)
            average_invoice_amount = calculate_average_invoice_amount(borrower_gst, trader_gst)
            print(average_invoice_amount)
            recency_invoice_data = calculate_recency_invoice(borrower_gst, trader_gst)
            print(recency_invoice_data)
            recent_ema = calculate_invoice_to_cash_flow(borrower_gst)
            choosen_data = "GST data"
            print("Chosen data: GST data")
        elif tally_recent_date:
            # Use Tally data
            invoice_frequency = calculate_invoice_frequency_tally(borrower_gst, trader_gst)
            average_invoice_amount = calculate_average_invoice_tally(borrower_gst, trader_gst)
            recency_invoice_data = calculate_recency_invoice_tally(borrower_gst, trader_gst)
            recent_ema = calculate_invoice_to_cash_flow_tally(borrower_gst)
            choosen_data = "Tally data"
            print("Chosen data: Tally data")

        operational_vintage = get_operational_vintage(trader_gst)
        # recent_ema = calculate_invoice_to_cash_flow(borrower_gst)
        
        
    ##static Metrics Assignments
    
        static_metrics = {
            "current_invoice_amount": invoice_data.get('current_invoice_amount'),  # Directly taken from input
            "average_invoice_amount": average_invoice_amount,  
            "invoice_frequency": invoice_frequency,
            "borrower_tax_compliance_score": borrower_compliance_score,
            "trader_tax_compliance_score": trader_compliance_score,
            "operational_vintage": operational_vintage  
        }
        print(static_metrics)
        
    
        
        # Use the most recent EMA value instead of the mean for "Invoice to Cash Flow"
        average_scores = {
            "invoice_to_cash_flow": recent_ema,  # Updated to use EMA       
            #,"Cash Flow to Revenue": data["Cash flow to revenue"].mean(),
            #"Tax to Invoice": data["tax to invoice"].mean()
        }
        
        # Normalize Invoice Frequency (higher is better)
        normalized_static_metrics = {"invoice_frequency": static_metrics["invoice_frequency"]}
            # Situation 1: Value is a string and needs to be converted to float.
        average_invoice_amount = static_metrics["average_invoice_amount"]
        try:
            current_invoice_amount = float(static_metrics["current_invoice_amount"])
            static_metrics["current_invoice_amount"] = current_invoice_amount  # update the dictionary
        except ValueError:
            print("Error: Current Invoice Amount is not a number.")
            current_invoice_amount = 0  # or some other appropriate default

        # Convert the 'Average Invoice Amount' to float and update in the dictionary
        try:
            average_invoice_amount = static_metrics["average_invoice_amount"]
            if isinstance(average_invoice_amount, pd.Series):
                average_invoice_amount = average_invoice_amount.iloc[0]

            average_invoice_amount = float(average_invoice_amount)
            static_metrics["average_invoice_amount"] = average_invoice_amount  # update the dictionary
        except ValueError:
            print("Error: Average Invoice Amount is not a number.")
            average_invoice_amount = 0  # or some other appropriate default

        # Now use the local variables for comparison, not the ones from the dictionary
        if current_invoice_amount > average_invoice_amount:
            detailed_insights.append("The invoice amount for this transaction is notably higher than the historical average, suggesting an unusually large deal.")

        # Now, you can perform the division. It's a good idea to use a try-except block here to catch any potential issues
        # with the division operation itself.
        try:
            invoice_ratio = static_metrics["current_invoice_amount"] / average_invoice_amount if average_invoice_amount else 0
        except ZeroDivisionError:
            invoice_ratio = 0 # re-raise the exception all re-raise the last exception which is useful for debugging

        # invoice_ratio = static_metrics["Current Invoice Amount"] / static_metrics["Average Invoice Amount"]
        if invoice_ratio < 1:
            normalized_static_metrics["current_invoice_amount"] = 100 + (1 - invoice_ratio) * 100
        elif invoice_ratio == 1:
            normalized_static_metrics["current_invoice_amount"] = 100
        else:
            normalized_static_metrics["current_invoice_amount"] = 100 - (invoice_ratio - 1) * 100
        print("normalized current invoice",normalized_static_metrics["current_invoice_amount"])
        
        # Normalize Tax Compliance Scores
        normalized_static_metrics["borrower_tax_compliance_score"] = static_metrics["borrower_tax_compliance_score"] * 10
        normalized_static_metrics["trader_tax_compliance_score"] = static_metrics["trader_tax_compliance_score"] * 10
        print("normalized_static_borrower_tax_compliance_score",normalized_static_metrics["borrower_tax_compliance_score"])
        print("normalized_static_trader_tax_compliance_score",normalized_static_metrics["trader_tax_compliance_score"])

        print("recency invoice: ", recency_invoice_data) 
        # Now, calculate the recency_score using the formula you've provided.
        
        recency_score = sum(recency_invoice_data[period] * recency_weights[period] for period in recency_invoice_data)
        static_metrics["recency_score"] = recency_score       
        # recency_score = calculate_recency_score(recency_invoice_data, recency_weights)
        normalized_static_metrics["recency_score"] = recency_score
        # For debugging, you might want to print the recency_score to verify its value.
        print(f"normalized recency_score: {recency_score}")

        
    # Call the function to calculate the Operational Vintage score
        operational_vintage = static_metrics["operational_vintage"]
        # try:
        #     operational_vintage = int(operational_vintage)
        # except ValueError:
        #     print("Error: operational_vintage is not an integer.")
        # operational_vintage = 0  # or any other appropriate default/fallback value

        vintage_score = calculate_vintage_score(operational_vintage)
        normalized_static_metrics["operational_vintage"] = vintage_score

        # Compute the weighted scores
        all_normalized_values = {**average_scores, **normalized_static_metrics}
        print("all_normalized_values",all_normalized_values)
        capped_weighted_scores = {}
        for metric, weight in weights.items():
            # Calculate the weighted value for the metric
            weighted_value = all_normalized_values.get(metric, 0) * weight
            
            # Apply capping based on the specified range
            if metric == "invoice_to_cash_flow":
                # For 'invoice_to_cash_flow', allow negative values and cap between the specified range
                capped_value = weighted_value  # Keep the value unchanged
            elif metric == "current_invoice_amount":
                # For 'current_invoice_amount', cap between the specified range (-20 to 20)
                min_value =  -20  # Minimum value based on the weight
                max_value =  20  # Maximum value based on the weight
                capped_value = min(max(weighted_value, min_value), max_value) 
            else:
                # For other metrics, cap between 0 and the specified range
                max_value = weight * 100  # Maximum value based on the weight
                capped_value = min(max(weighted_value, 0), max_value)  # Cap the value between 0 and max_value
            # Update the capped weighted scores dictionary with the capped value
            capped_weighted_scores[metric] = capped_value
            print(f"capped_value for {metric}: {capped_value}")
        base_score = sum(capped_weighted_scores.values())
        # Add the weight of 'data_source' directly to the final score
        data_source_weight = weights.get("data_source", 0)  # This weight is directly added, no multiplication needed
        # If chosen_data is "Tally", consider the data_source metric in the calculation
        if choosen_data == "Tally data":
            # Add the data_source_weight to the base_score if the chosen data is from Tally
            base_score += data_source_weight
            base_score = min(base_score, 100)  # Cap the score at 100
            # Ensure the score does not go below 0
            base_score = round(base_score, 2)
        elif choosen_data == "GST data":
            # If the chosen data is GST data, round the base_score to 2 decimal places
            base_score = min(base_score, 100)  # Cap the score at 100
            # Ensure the score does not go below 0
            base_score = round(base_score, 2)
        
        print(base_score,"base_score")
        
        # Load additional metrics from request
        additional_metrics = {
            "grn_present": additional_metrics_input.get('grn_present', False),
            "e_invoice_present": additional_metrics_input.get('e_invoice_present', False),
            "e_way_bill_present": additional_metrics_input.get('e_way_bill_present', False),
            "trader_partner_confirmation": additional_metrics_input.get('trader_partner_confirmation', False)
        }
        # Calculate the sum of weights for the present additional metrics
        metric_total = sum(additional_weights[metric] for metric, present in additional_metrics.items() if present)
        print(metric_total,"metric_total")
        # Calculate 25% of this sum and then multiply it with the base score for enhancement total
        enhancement_factor = overall_weight * metric_total  # This is the percentage to apply to the base score
        print(enhancement_factor,"enhancement_factor")
        enhancement_total = enhancement_factor * base_score
        print(enhancement_total,"enhancement_total")

        # Calculate final score and cap it at 100
        # final_score = base_score + enhancement_total
        # final_score=round(final_score, 2)
        # Calculate final score and apply a cap of 100
        final_score = base_score + enhancement_total
        final_score = min(final_score, 100)  # Cap the score at 100
        # final_score = max(final_score, 0)    # Ensure the score does not go below 0
        final_score = round(final_score, 2)
         # Calculate the impact of each metric on the final score
        metric_impact = {metric: value/final_score for metric, value in capped_weighted_scores.items()}
        # major_contributors = sorted(metric_impact.items(), key=lambda x: x[1], reverse=True)[:3]
        major_contributors = metric_impact.items()
        # Instead, you should convert it to a dictionary like so:
        
        # Output
        print(f"Credit Score: {final_score:.2f}")
        print("\nMetric Contributions:")
        formatted_metric_contributions = {}
        for metric, impact in metric_impact.items():
            # Format the contribution as a string with a percentage
            contribution = f"{impact*100:.2f}%"
            formatted_metric_contributions[metric] = contribution
            print(formatted_metric_contributions)
        detailed_insights = []
        if static_metrics["current_invoice_amount"] > static_metrics["average_invoice_amount"]:
            detailed_insights.append("The invoice amount for this transaction is notably higher than the historical average, suggesting an unusually large deal.")
        
        # Recent Invoice Activity
        if recency_invoice_data["1_3_months"] > sum(recency_invoice_data.values()) / 2:  # more than half invoices in last 3 months
            detailed_insights.append("There's been an unusually high number of transactions in the last 3 months, indicating increased recent activity.")
        
        # Operational Vintage
        if static_metrics["operational_vintage"] < 12:  # less than 12 months
            detailed_insights.append("The company is relatively new, having been operational for less than a year.")
        
        
                # Insights dictionary with conditions and messages for each metric
        insights = {
            "current_invoice_amount": {
                "positive": "The transaction size aligns favorably with our expectations based on historical trends.",
                "negative": "The transaction size deviates from typical patterns, suggesting potential irregularities.",
                "condition": lambda metrics: metrics["current_invoice_amount"] <= metrics["average_invoice_amount"]
            },
            "invoice_frequency": {
                "positive": "Regular transactions between the parties indicate a robust business relationship.",
                "negative": "Infrequent transactions may suggest sporadic or inconsistent business dealings.",
                "condition": lambda metrics: metrics["invoice_frequency"] > 5  # Assuming more than 5 transactions is regular
            },
            "borrower_tax_compliance_score": {
                "positive": "The borrower showcases commendable financial discipline and compliance.",
                "negative": "The borrower's financial practices raise potential concerns.",
                "condition": lambda metrics: metrics["borrower_tax_compliance_score"] > 7  # Score above 7 is good
            },
            "trader_tax_compliance_score": {
                "positive": "The trader involved has a commendable track record of financial responsibility.",
                "negative": "The trader's financial practices may warrant closer scrutiny.",
                "condition": lambda metrics: metrics["trader_tax_compliance_score"] > 7  # Score above 7 is good
            },
            "recency_score": {
                "positive": "Recent transaction activities suggest a growth trajectory or a significant business engagement.",
                "negative": "A potential inconsistency or irregularity is indicated by recent transaction patterns.",
                "condition": lambda metrics: metrics["recency_score"] > 0.5  # Score above 0.5 is recent and positive                 
            },
            "operational_vintage": {
                "positive": "The company's operational history signifies market experience and stability.",
                "negative": "The company's relatively recent entry into the market may come with navigational challenges.",
                "condition": lambda metrics: metrics["operational_vintage"] >= 24  # 12 months or more is stable
            }
        }

        # Function to generate insights based on current metrics
        def generate_insights(metrics):
            positive_insights = []
            negative_insights = []

            for metric, details in insights.items():
                # Debug: Print the metric value
                

                # Ensure the value is an integer if it's expected to be
                current_value = metrics.get(metric)
                print(f"Debug: {metric} value: ", metrics.get(metric))
                if metric == "invoice_frequency" and isinstance(current_value, str):
                    try:
                        # Try converting the value to an integer
                        current_value = int(current_value)
                    except ValueError:
                        # Handle the case where the conversion fails
                        print("Error: Cannot convert Invoice Frequency to an integer.")
                        current_value = 0  # or some other appropriate fallback

                # Update the metrics dictionary with the corrected value
                metrics[metric] = current_value

                # Proceed with the original logic
                if details["condition"](metrics):
                    positive_insights.append(details["positive"])
                else:
                    negative_insights.append(details["negative"])
            # Add a default observation if there are no specific negative insights
            if not negative_insights:
                default_observation = "Comprehensive analysis reveals a stable and promising financial engagement, with no areas of concern identified."
                negative_insights.append(default_observation)


            return positive_insights, negative_insights
                # Generate insights based on the computed metrics
        positive_insights, negative_insights = generate_insights(static_metrics)

        # Display Insights
        print(f"Credit Score: {final_score:.2f}\n")
        print("Highlights:")
        for insight in positive_insights:
            print(f"- {insight}")

        print("\nObservations:")
        for insight in negative_insights:
            print(f"- {insight}")
            
        base_verdict = ""
        sentiment = ""
        
        if final_score >= 50:
            base_verdict = "This transaction appears strongly favorable."
        elif final_score >= 40:
            base_verdict = "This transaction seems generally favorable."
        elif final_score >= 30:
            base_verdict = "This transaction presents a neutral standpoint."
        else:
            base_verdict = "Exercising caution is recommended."

        # Add sentiment based on positive vs. negative insights
        if len(positive_insights) > len(negative_insights):
            sentiment = "Overall, the indicators suggest a good potential for financing."
        elif len(positive_insights) < len(negative_insights):
            sentiment = "However, there are several points of concern that warrant further due diligence."
        
        # Combining base verdict and sentiment
        verdict = f"{base_verdict} {sentiment}"
        
        print(f"\nFinal Verdict: {verdict}")
        '''    
        print("\nMajor Contributors:")
        for metric, impact in major_contributors:
            reason = f"High {metric}" if impact > 0.1 else f"Low {metric}"
            print(f"{metric}: {impact*100:.2f}% - Reason: {reason}")
        '''

        # metric_contributions = {
        #     metric: contribution for metric, contribution in major_contributors  # assuming major_contributors is a list of tuples
        # }
        


    # Construct the output dictionary according to your specified structure

# Before setting up transaction_log_entry, check if tally_recent_date is None
        # if tally_recent_date is None:
        #     comparison_result = None
        # # else:
        #     comparison_result = {
        #         "percentage_difference": percentage_difference,
        #         "filtered_gst_data": filtered_gst_data if filtered_gst_data is not None else "No data",
        #         "filtered_tally_data": filtered_tally_data if filtered_tally_data is not None else "No data",
        #         "compare_result_message": compare_result_message
        #     }
        transaction_log_entry = {
                "request_id": transaction_uuid,
                "timestamp": timestamp,
                "input": {
                    "borrower_gst": invoice_data['borrower_gst'],
                    "trader_gst": invoice_data['trader_gst'],
                    "current_invoice_amount": invoice_data['current_invoice_amount']
                },
                "output": {
                    "credit_score": final_score,
                    "request_id": transaction_uuid,
                    "final_verdict": verdict,
                    "highlights": positive_insights,
                    "observations": negative_insights
                },
                # "comparison_result": comparison_result,
                "gst_recent_updated_date":gst_recent_date,
                "tally_recent_updated_date":tally_recent_date,
                "invoice_to_cashflow" :recent_ema ,
                "recency_invoice_data":recency_invoice_data,
                "static_metrics": static_metrics,
                "metric_contributions":  formatted_metric_contributions,
                "choosen_data":choosen_data 
            }
        def convert_all_timestamps(obj):
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: convert_all_timestamps(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_all_timestamps(elem) for elem in obj]
            return obj
        # Convert all Timestamps in the transaction_log_entry to strings
        transaction_log_entry = convert_all_timestamps(transaction_log_entry)
        def convert_datetime_to_string(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    obj[key] = convert_datetime_to_string(value)
            elif isinstance(obj, list):
                obj = [convert_datetime_to_string(item) for item in obj]
            elif isinstance(obj, datetime):
                return obj.isoformat()
            return obj

        # Convert all datetime objects in transaction_log_entry to strings
        transaction_log_entry = convert_datetime_to_string(transaction_log_entry)
        # Write the transaction log entry to your JSON log file
        file_name = f"{transaction_uuid}.json"
        with open(file_name, 'w') as log_file:
            json.dump(transaction_log_entry, log_file) # Newline separates multiple entries in the log file
        # Constructing the file path
        current_date = datetime.now()
        year = current_date.strftime("%Y")
        month = current_date.strftime("%m")
        day = current_date.strftime("%d")

        bucket_name = 'YOUR_AUDIT_BUCKET_NAME'
        s3_file_path = f"credit_recommendation_results/year={year}/month={month}/day={day}/{file_name}"
        uploaded = upload_file_to_s3(file_name, bucket_name, s3_file_path)
        if uploaded:
            print(f"File '{file_name}' uploaded as '{s3_file_path}' in the bucket '{bucket_name}'.")
        else:
            print("File upload failed.")
    
        # Prepare the response
        # Construct the ordered response
        response = OrderedDict([
            ("base_score",base_score),
            ("credit_score", final_score),
            ("request_id", transaction_uuid),
            ("timestamp", timestamp),
            ("highlights", positive_insights),
            ("observations", negative_insights),
            ("final_verdict", verdict)
        ])

        # Add metrics contribution if debug flag is enabled
        if data.get('debug', False):
            response["Metric Contributions"] = major_contributors

            # Convert the OrderedDict to a JSON string
        response_json = json.dumps(response)
        
        # Return the JSON string
        return response_json


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8114)
