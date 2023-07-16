# Applicant - Employee Match App and Algorithm

## The Company Tech Interview - Context  

The Company's main product, the retention prediction, provides to our clients the likelihood of an applicant
being retained for the different jobs they apply to.  
  
The prediction is generated with our proprietary AI models, which are trained by combining two
datasets:  
  
1) The applicants and the jobs they applied to - the Application Data  
2) The applicant's tenures once they are hired for specific jobs - the Hire/Termination Data  
  
The models learn the characteristics of applicants that were hired and had long tenures. They are
then capable of making retention predictions for future applicants.  
  
The caveat is that the two datasets come from different systems and there are no direct identifiers
to match a person that applied for a job (an "applicant"), to that person being hired for a particular
job (a "hire").  
  
To bridge this gap, we developed an algorithm that matches the applicant to the hire. The version
you are receiving is a simplification of the actual algorithm: it does the matching through the
person's first and last name, and doesn't take the job information into account.  
  
In the real world, people's names don't align so neatly. On the day of the interview, you'll
implement a feature related to that. More details will be provided then.  
  
Make sure you have your environment setup before the day of the interview and that you can run
the examples described in the README.  
  