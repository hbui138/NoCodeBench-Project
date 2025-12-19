# check_data.py
from datasets import load_dataset

print("Downloading dataset NoCode-bench Verified...")
# Download the NoCode-bench Verified dataset
dataset = load_dataset('NoCode-bench/NoCode-bench_Verified', split='test')

print(f"Dataset size: {len(dataset)}")

# Print an example from the dataset
sample = dataset[0]
print("\n--- Example for Instance ID: ", sample['instance_id'])
print("--- Input for Model (Problem Statement):")
print(sample['problem_statement'][:500] + "...") # First 500 characters