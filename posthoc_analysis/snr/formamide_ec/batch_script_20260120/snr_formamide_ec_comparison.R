library(tidyverse)
library(patchwork)
library(ggrepel)
library(ggbeeswarm)
library(rstatix)
library(ggprism)

## read in files

files <- list.files(
    path = "./posthoc_analysis/snr/formamide_ec/batch_script_20260120/bf_output",
    pattern = "*.csv",
    full.names = TRUE
) %>%
    set_names(~tools::file_path_sans_ext(basename(.x)))

output_list <- files %>%
    purrr::map(read_csv) %>%
    purrr::imap(~{
        .x %>%
            mutate(channel = case_when(
                str_detect(.y, "ch1") ~ "chinmo",
                str_detect(.y, "ch2") ~ "ago1",
                TRUE ~ "none"
            )) %>%
            mutate(denaturant = case_when(
                str_detect(.y, "groupA|groupB") ~ "Formamide",
                str_detect(.y, "groupC|groupD") ~ "EC",
            )) %>%
            mutate(block = case_when(
                str_detect(.y, "groupA|groupC") ~ "Noblock",
                str_detect(.y, "groupB|groupD") ~ "Block",
            )) %>%
            mutate(file = .y)
    })

output_df <- output_list %>%
    purrr::map_dfr(~dplyr::select(.x, c("snr", "channel", "denaturant", "block", "file"))) %>%
    mutate(group = str_c(denaturant, block, sep = "_"))

output_df %>%
    ggplot(aes(x = group, y = snr, fill = denaturant)) + 
    geom_violin() +
    geom_boxplot(width = 0.2) + 
    theme_minimal()

output_df %>% colnames()

output_df_summary <- output_df %>%
    group_by(group, file, denaturant, block, channel) %>%
    summarise(
        median_snr = median(snr),
        mean_snr = mean(snr)
        ) %>%
    ungroup()

output_df_summary %>%
    group_by(group) %>%
    shapiro_test(mean_snr)

tukey_test_result <- output_df_summary %>%
    tukey_hsd(mean_snr ~ group)

View(tukey_test_result)

tukey_test_result_todisplay <- tukey_test_result %>%
    dplyr::slice(c(1,2,5,6)) %>%
    add_xy_position()

output_df_summary %>%
    mutate(group = fct_rev(group)) %>%
    ggplot(aes(x = group, y = mean_snr)) + 
    geom_quasirandom(size = 3, aes(colour = denaturant)) + 
    add_pvalue(data = tukey_test_result_todisplay, 
        label = "p.adj.signif",
        label.size = 4,
        inherit.aes = FALSE,
        y.position = c(2.405, 2.415, 2.43, 2.405)
    ) +
    labs(
        title = "Formamide and EC are comparable FISH denaturants",
        subtitle = "Blocking agents DO make a difference",
        x = "",
        y = "Mean smFISH signal-to-noise ratio (SNR)",
        caption = "EC = Ethylene Carbonate"
    ) + 
    theme_bw(base_size = 15) +
    theme(
        axis.text.x = element_text(angle = 45, vjust = 1, hjust = 1)
    )

ggsave(
    "./posthoc_analysis/snr/formamide_ec/snr_formamide_ec_comparison.png",
    width = 7,
    height = 7, 
    dpi = 300
)


## Formamide only
# subset the summary dataframe to Formamide groups and run a t-test
formamide_df <- output_df_summary %>%
    filter(denaturant == "Formamide")

# perform two‑sample t-test comparing blocked vs noblock
formamide_ttest <- formamide_df %>%
    t_test(mean_snr ~ block) %>%
    add_significance() %>%
    add_xy_position()
print(formamide_ttest)

# plot with p-value annotation
formamide_df %>%
    mutate(block = fct_rev(block)) %>%
    ggplot(aes(x = block, y = mean_snr, fill = block)) +
    # geom_violin(trim = FALSE) +
    geom_boxplot(width = 0.2, outlier.shape = NA) +
    geom_quasirandom(size = 2, alpha = 0.6) +
    add_pvalue(data = formamide_ttest, 
               label = "p.signif", 
               inherit.aes = FALSE,
               label.size = 4,
               y.position = max(formamide_df$mean_snr) * 1.005
               ) +
    labs(
        title = "Effect of blocking agents on smFISH SNR",
        x = "Blocking",
        y = "Mean smFISH signal-to-noise ratio (SNR)"
    ) +
    theme_bw(base_size = 11) +
    theme(legend.position = "none")

# save the formamide-only figure if desired
ggsave(
    "./posthoc_analysis/snr/formamide_ec/snr_formamide_formamide_only.png",
    width = 6,
    height = 5,
    dpi = 300
)
