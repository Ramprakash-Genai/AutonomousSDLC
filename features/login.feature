Feature: Login
  Scenario: Valid Login
    Given user navigates to "https://fa-epvg-test-saasfaprod1.fa.ocs.oraclecloud.com:443/fscmUI/faces/FuseWelcome"
    When user fills "Trainee User Functional" into textbox "Username" in signin page
    And user fills "@+34Ll8I_|ib" into textbox "Password" in signin page
    When user clicks button "Next" in signin page
    Then user should see text "Enter the passcode sent to the" in signin page
    When user clicks button "Try another way" in signin page
    Then user should see text "Choose how you would like to authenticate." in signin page
    When user clicks button "Bypass Code" in signin page
    Then user should see text "Enter the bypass code." in signin page
    When user fills "380871860776" into textbox below text "Enter the bypass code." in signin page
    When user clicks button "Verify" in signin page
    When user clicks the link Procurement in Oracle welcome page        
    When user clicks tab "Procurement" within tablist Navigation Tab in Oracle welcome page
    Then user should see the link "Purchase Requisitions (New)" is visible in Oracle welcome page
    Then user click the link "Purchase Requisitions (New)" in Oracle welcome page
    
    When user clicks button "Create Noncatalog Request" in Procurement page
    When user fills "my item" into textbox "Item Description" in Noncatalog request page

    When user clicks combobox "Category" in Noncatalog request page
    Then user fills "Cylinder" into combobox "Category" in Noncatalog request page    
    When user fills "100" into textbox "Price" in Noncatalog request page
    Then user clicks combobox "UOM" in Noncatalog request page
    Then user fills "Box" into combobox "UOM" in Noncatalog request page
    When user fills "my item" into textbox "Item Description" in Noncatalog request page
    When user clicks button "Add to Cart" in Noncatalog request page
    